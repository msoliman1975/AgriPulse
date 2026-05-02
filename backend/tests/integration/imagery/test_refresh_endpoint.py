"""POST /blocks/{id}/imagery/refresh enqueues discover_scenes per subscription.

The endpoint itself is purely an enqueue — `discover_scenes.delay()`
hands a Celery task off to the broker. We assert two contracts here:

  1. The HTTP response carries the right `queued_subscription_ids`.
  2. Calling the task body directly against a fake provider produces
     a pending ingestion-job row with the expected scene_id.

We can't run the task chain in Celery's `task_always_eager` mode here
because eager invocation calls `asyncio.run()` from inside the test's
already-running loop and crashes with "asyncio.run() cannot be called
from a running event loop". The cassette-driven full pipeline test in
PR-C / a future PR will exercise that code path through Celery proper.
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
    """Stub ImageryProvider — returns a hard-coded scene + raw_bands."""

    code = "sentinel_hub"

    def __init__(self, scenes: tuple[DiscoveredScene, ...]) -> None:
        self._scenes = scenes

    async def discover(self, **_: Any) -> tuple[DiscoveredScene, ...]:
        return self._scenes

    async def fetch(self, **_: Any) -> FetchResult:
        return FetchResult(
            cog_bytes=b"II*\x00fake-cog",
            band_order=("blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"),
        )

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_refresh_returns_queued_subscription_ids(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-refresh-http",
        name="Imagery Refresh HTTP",
        contact_email="ops@refresh-http.test",
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
        farm_id, block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        sub_id = sub_resp.json()["id"]

        # Empty queue Celery — `.delay()` will try to enqueue. With no
        # broker reachable it errors. Patch the task's `delay` to a
        # no-op so the HTTP path is testable in isolation.
        from app.modules.imagery.tasks import discover_scenes

        captured: list[tuple[str, str]] = []

        def _capture(*args: object, **kwargs: object) -> None:
            captured.append(tuple(args))  # type: ignore[arg-type]

        original_delay = discover_scenes.delay
        discover_scenes.delay = _capture  # type: ignore[method-assign]
        try:
            resp = await client.post(f"/api/v1/blocks/{block_id}/imagery/refresh")
        finally:
            discover_scenes.delay = original_delay  # type: ignore[method-assign]

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["queued_subscription_ids"] == [sub_id]
    # `.delay()` was called once with the right args.
    assert len(captured) == 1
    assert captured[0][0] == sub_id
    assert captured[0][1] == tenant.schema_name


@pytest.mark.asyncio
async def test_discover_scenes_creates_pending_jobs(
    admin_session: AsyncSession,
) -> None:
    """The task body itself: provider returns one scene → one pending job."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-refresh-task",
        name="Imagery Refresh Task",
        contact_email="ops@refresh-task.test",
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

    # Wire the fake provider, also short-circuit the task's chained
    # `acquire_scene.delay()` so we don't try to enqueue.
    fake_scenes = (
        DiscoveredScene(
            scene_id="S2A_TEST_20260301",
            scene_datetime=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("12.50"),
            geometry_geojson={"type": "Polygon", "coordinates": []},
        ),
    )
    imagery_tasks.set_provider_factory(lambda: _FakeProvider(fake_scenes))
    from app.modules.imagery.tasks import acquire_scene

    original_delay = acquire_scene.delay
    acquire_scene.delay = lambda *a, **k: None  # type: ignore[method-assign]
    try:
        # Direct invocation of the task's async core — no asyncio.run wrapper.
        result = await imagery_tasks._discover_scenes_async(sub_id, tenant.schema_name)
    finally:
        acquire_scene.delay = original_delay  # type: ignore[method-assign]
        imagery_tasks.reset_provider_factory()

    assert result["discovered"] == 1
    assert result["queued"] == 1
    assert result["skipped_cloud"] == 0

    # Verify the job row landed in pending state.
    rows = (
        await admin_session.execute(
            text(f'SELECT scene_id, status FROM "{tenant.schema_name}".' "imagery_ingestion_jobs")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == "S2A_TEST_20260301"
    assert rows[0][1] == "pending"


@pytest.mark.asyncio
async def test_discover_scenes_marks_high_cloud_as_skipped(
    admin_session: AsyncSession,
) -> None:
    """A scene above the visualization threshold becomes status='skipped_cloud'."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-cloud-skip",
        name="Imagery Cloud Skip",
        contact_email="ops@cloud-skip.test",
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

    cloudy = (
        DiscoveredScene(
            scene_id="S2A_CLOUDY",
            scene_datetime=datetime(2026, 3, 5, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("85.00"),  # > viz threshold (60%)
            geometry_geojson={"type": "Polygon", "coordinates": []},
        ),
    )
    imagery_tasks.set_provider_factory(lambda: _FakeProvider(cloudy))
    from app.modules.imagery.tasks import acquire_scene

    original_delay = acquire_scene.delay
    acquire_scene.delay = lambda *a, **k: None  # type: ignore[method-assign]
    try:
        result = await imagery_tasks._discover_scenes_async(sub_id, tenant.schema_name)
    finally:
        acquire_scene.delay = original_delay  # type: ignore[method-assign]
        imagery_tasks.reset_provider_factory()

    assert result["queued"] == 0
    assert result["skipped_cloud"] == 1

    rows = (
        await admin_session.execute(
            text(f'SELECT scene_id, status FROM "{tenant.schema_name}".' "imagery_ingestion_jobs")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][1] == "skipped_cloud"


@pytest.mark.asyncio
async def test_discover_scenes_idempotent_on_rerun(
    admin_session: AsyncSession,
) -> None:
    """Re-running discovery with the same scene_id is a no-op (gate criterion 8)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="imagery-idemp",
        name="Imagery Idempotent",
        contact_email="ops@idemp.test",
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

    scenes = (
        DiscoveredScene(
            scene_id="S2A_REPEAT",
            scene_datetime=datetime(2026, 3, 10, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("10.00"),
            geometry_geojson={"type": "Polygon", "coordinates": []},
        ),
    )
    imagery_tasks.set_provider_factory(lambda: _FakeProvider(scenes))
    from app.modules.imagery.tasks import acquire_scene

    original_delay = acquire_scene.delay
    acquire_scene.delay = lambda *a, **k: None  # type: ignore[method-assign]
    try:
        first = await imagery_tasks._discover_scenes_async(sub_id, tenant.schema_name)
        second = await imagery_tasks._discover_scenes_async(sub_id, tenant.schema_name)
    finally:
        acquire_scene.delay = original_delay  # type: ignore[method-assign]
        imagery_tasks.reset_provider_factory()

    # First run creates one queued job; second sees the same scene already
    # ingested and creates none.
    assert first["queued"] == 1
    assert second["queued"] == 0
    rows = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".' "imagery_ingestion_jobs")
        )
    ).scalar_one()
    assert rows == 1
