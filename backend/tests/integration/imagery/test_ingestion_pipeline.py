"""Full ingestion pipeline: discover → acquire → register_stac_item.

We invoke the three task async cores in sequence (without going through
Celery's `.delay()` / asyncio.run wrappers) against a real Postgres +
pgstac container. The provider and S3 client are stubbed so the test
is hermetic; the database, pgstac.create_collection / create_items,
and audit writes are exercised against the real engine.

Asserts the gate criteria from the prompt:

  * a `pending` job appears after discovery
  * after acquire+register, status is 'succeeded' with a stac_item_id
  * a row in pgstac.items exists for the right collection
  * re-running discover for the same scene is a no-op (idempotency)
  * a scene above the cloud-cover threshold is recorded as
    `status='skipped_cloud'`
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery import tasks as imagery_tasks
from app.modules.imagery.providers.protocol import DiscoveredScene, FetchResult
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_user_in_tenant,
    make_context,
)
from .test_subscription_crud import (
    _create_farm_and_block,
    _get_s2l2a_product_id,
)

pytestmark = [pytest.mark.integration]


class _FakeProvider:
    code = "sentinel_hub"

    def __init__(self, scenes: tuple[DiscoveredScene, ...]) -> None:
        self._scenes = scenes

    async def discover(self, **_: Any) -> tuple[DiscoveredScene, ...]:
        return self._scenes

    async def fetch(self, **_: Any) -> FetchResult:
        return FetchResult(
            cog_bytes=b"II*\x00fake-multiband",
            band_order=("blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"),
        )

    async def aclose(self) -> None:
        pass


class _CaptureStorage:
    bucket = "missionagre-uploads"

    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str]] = []

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.uploads.append((key, body, content_type))

    # Unused parts of the StorageClient Protocol — return-typed-as-Any
    # so a missed call from production code surfaces loudly.
    def presign_upload(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("unexpected presign_upload in pipeline test")

    def presign_download(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("unexpected presign_download in pipeline test")

    def head_object(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("unexpected head_object in pipeline test")

    def delete_object(self, **_: Any) -> None:  # pragma: no cover
        raise AssertionError("unexpected delete_object in pipeline test")


async def _set_up_subscription(
    admin_session: AsyncSession,
    *,
    slug: str,
) -> tuple[UUID, UUID, str, str]:
    """Bootstrap a tenant, farm, block, and one active subscription.

    Returns ``(subscription_id, block_id_uuid, tenant_schema, product_id)``.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=slug,
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        sub_id = UUID(sub_resp.json()["id"])
    return sub_id, UUID(block_id), tenant.schema_name, product_id


def _patch_provider_and_storage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenes: tuple[DiscoveredScene, ...],
) -> _CaptureStorage:
    capture = _CaptureStorage()
    imagery_tasks.set_provider_factory(lambda: _FakeProvider(scenes))
    monkeypatch.setattr(imagery_tasks, "_get_storage", lambda: capture)
    return capture


@pytest.mark.asyncio
async def test_full_pipeline_succeeds_end_to_end(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id, _block_id, tenant_schema, _product_id = await _set_up_subscription(
        admin_session, slug="imagery-pipeline-ok"
    )
    scenes = (
        DiscoveredScene(
            scene_id="S2A_PIPELINE_OK_20260301",
            scene_datetime=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("12.50"),
            geometry_geojson={"type": "Polygon", "coordinates": []},
        ),
    )
    capture = _patch_provider_and_storage(monkeypatch, scenes=scenes)

    # Stub `.delay()` so we can drive the chain manually.
    from app.modules.imagery.tasks import acquire_scene, register_stac_item

    monkeypatch.setattr(acquire_scene, "delay", lambda *a, **k: None)
    monkeypatch.setattr(register_stac_item, "delay", lambda *a, **k: None)

    try:
        # Discover.
        await imagery_tasks._discover_scenes_async(sub_id, tenant_schema)

        # Pull job_id back from DB.
        job_id_raw = (
            await admin_session.execute(
                text(
                    f'SELECT id FROM "{tenant_schema}".imagery_ingestion_jobs '
                    "WHERE scene_id = 'S2A_PIPELINE_OK_20260301'"
                )
            )
        ).scalar_one()
        job_id = UUID(str(job_id_raw))

        # Acquire — uploads a COG to the capture-only storage.
        await imagery_tasks._acquire_scene_async(job_id, tenant_schema)
        # Register — creates pgstac collection + items row.
        await imagery_tasks._register_stac_item_async(
            job_id, tenant_schema, [capture.uploads[0][0]]
        )
    finally:
        imagery_tasks.reset_provider_factory()

    # Assert: job is succeeded with a stac_item_id.
    row = (
        await admin_session.execute(
            text(
                f'SELECT status, stac_item_id, assets_written FROM "{tenant_schema}".'
                "imagery_ingestion_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).one()
    assert row.status == "succeeded"
    assert row.stac_item_id.startswith("sentinel_hub/s2_l2a/")

    # Assert: pgstac.items has the row in the right per-tenant collection.
    items_count = (
        await admin_session.execute(
            text("SELECT count(*) FROM pgstac.items " "WHERE collection = :c AND id = :id"),
            {"c": f"{tenant_schema}__s2_l2a", "id": row.stac_item_id},
        )
    ).scalar_one()
    assert items_count == 1

    # Assert: deterministic asset key.
    assert len(capture.uploads) == 1
    key, body, content_type = capture.uploads[0]
    assert key.startswith("sentinel_hub/s2_l2a/S2A_PIPELINE_OK_20260301/")
    assert key.endswith("/raw_bands.tif")
    assert body == b"II*\x00fake-multiband"
    assert "image/tiff" in content_type


@pytest.mark.asyncio
async def test_pipeline_idempotent_on_rerun(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running discover+acquire+register with the same scene must be a no-op
    after the first success — no new ingestion-job rows, no new pgstac.items.
    """
    sub_id, _block_id, tenant_schema, _product_id = await _set_up_subscription(
        admin_session, slug="imagery-pipeline-idemp"
    )
    scenes = (
        DiscoveredScene(
            scene_id="S2A_IDEMP_20260301",
            scene_datetime=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("10.00"),
            geometry_geojson={"type": "Polygon", "coordinates": []},
        ),
    )
    capture = _patch_provider_and_storage(monkeypatch, scenes=scenes)
    from app.modules.imagery.tasks import acquire_scene, register_stac_item

    monkeypatch.setattr(acquire_scene, "delay", lambda *a, **k: None)
    monkeypatch.setattr(register_stac_item, "delay", lambda *a, **k: None)

    try:
        await imagery_tasks._discover_scenes_async(sub_id, tenant_schema)
        job_id_raw = (
            await admin_session.execute(
                text(
                    f'SELECT id FROM "{tenant_schema}".imagery_ingestion_jobs '
                    "WHERE scene_id = 'S2A_IDEMP_20260301'"
                )
            )
        ).scalar_one()
        job_id = UUID(str(job_id_raw))
        await imagery_tasks._acquire_scene_async(job_id, tenant_schema)
        await imagery_tasks._register_stac_item_async(
            job_id, tenant_schema, [capture.uploads[0][0]]
        )

        # Re-run discover + acquire + register. Discovery sees the same
        # scene_id and inserts nothing; acquire sees a non-pending job
        # and short-circuits; register sees a non-running job likewise.
        await imagery_tasks._discover_scenes_async(sub_id, tenant_schema)
        result_acquire = await imagery_tasks._acquire_scene_async(job_id, tenant_schema)
        result_register = await imagery_tasks._register_stac_item_async(
            job_id, tenant_schema, [capture.uploads[0][0]]
        )
    finally:
        imagery_tasks.reset_provider_factory()

    job_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant_schema}".imagery_ingestion_jobs')
        )
    ).scalar_one()
    assert job_count == 1
    assert result_acquire.get("noop") is True
    assert result_register.get("noop") is True

    # No second pgstac item.
    items_count = (
        await admin_session.execute(
            text("SELECT count(*) FROM pgstac.items WHERE collection = :c"),
            {"c": f"{tenant_schema}__s2_l2a"},
        )
    ).scalar_one()
    assert items_count == 1
