"""Fetching one pass for the whole farm, rather than one per block.

The block path leaves ground nobody drew a block around unmeasured — 50.3 of
203.4 feddan on the reference farm. These tests cover the path that fixes it,
and the switch that keeps it from turning itself on:

  * a farm with ``fetch_farm_aoi`` off is never swept, because 0074 created an
    active farm subscription for EVERY farm and a sweep without the gate would
    start fetching a second, larger AOI platform-wide;
  * discovery is idempotent on (subscription, scene), like the block path;
  * an acquired pass writes its raster under the FARM's aoi hash and records
    ``source='fetched'`` with no blocks_merged;
  * a stitched surface never overwrites a fetched one for the same pass — the
    fetched one covers strictly more ground.

The provider and the rasterio reader are stubbed; the database is real.
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
from .test_ingestion_pipeline import _CaptureStorage
from .test_subscription_crud import _create_farm_and_block, _get_s2l2a_product_id

pytestmark = [pytest.mark.integration]

SCENE = DiscoveredScene(
    scene_id="S2A_FARM_AOI_20260301",
    scene_datetime=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
    cloud_cover_pct=Decimal("4.00"),
    geometry_geojson={"type": "Polygon", "coordinates": []},
)


class _FakeProvider:
    code = "sentinel_hub"

    def __init__(self, scenes: tuple[DiscoveredScene, ...]) -> None:
        self._scenes = scenes
        self.fetched_aois: list[dict[str, Any]] = []

    async def discover(self, **_: Any) -> tuple[DiscoveredScene, ...]:
        return self._scenes

    async def fetch(self, **kwargs: Any) -> FetchResult:
        self.fetched_aois.append(kwargs["aoi_geojson_utm36n"])
        return FetchResult(
            cog_bytes=b"II*\x00fake-farm-multiband",
            band_order=("blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"),
        )

    async def aclose(self) -> None:
        pass


def _stub_rasterio(
    monkeypatch: pytest.MonkeyPatch,
    *,
    grid: dict[str, Any] | None = None,
    index_value: float = 0.5,
) -> list[str]:
    """Replace the raster read/write, recording which aoi hash was used.

    With ``grid`` supplied the doubles hand back a REAL profile and real
    index arrays, so the per-block zonal path downstream runs for real
    against the farm grid. Without it they stay empty, which is enough for
    the tests that only care about prefixes and job state.
    """
    import numpy as np

    from app.modules.imagery import _rasterio_io

    seen_hashes: list[str] = []
    seen_product_codes: list[str] = []
    profile: dict[str, Any] = grid or {"transform": None}
    if grid is not None:
        rasters = {
            code: np.full((grid["height"], grid["width"]), index_value, dtype="float32")
            for code in ("ndvi", "ndmi")
        }
    else:
        rasters = {}

    def fake_load(
        uri: str,
        *,
        band_names: tuple[str, ...],
        aoi_geojson_utm36n: dict,
        product_code: str = "s2_l2a",
    ) -> tuple:
        # `product_code` mirrors the real signature: it selects which
        # masking rules the trailing quality band follows. Accepting it
        # here rather than swallowing kwargs keeps this double honest —
        # see the note on `fake_compute` below.
        seen_product_codes.append(product_code)
        return ({b: None for b in band_names}, None, None, profile)

    def fake_compute(**kwargs: Any) -> tuple:
        seen_hashes.append(kwargs["aoi_hash"])
        # The real signature returns dict[index_code -> written key]. This
        # double used to return a bare list, which is how a caller iterating
        # it got index CODES where object paths belonged and the test still
        # passed. A double that does not match the contract cannot catch the
        # bug the contract exists to prevent.
        keys = {code: f"{kwargs['aoi_hash']}/{code}.tif" for code in ("ndvi", "ndmi")}
        return ({}, keys, rasters)

    monkeypatch.setattr(_rasterio_io, "load_raw_bands_and_aggregate", fake_load)
    monkeypatch.setattr(_rasterio_io, "compute_and_write_indices", fake_compute)
    return seen_hashes


async def _farm_grid(session: AsyncSession, schema: str, farm_id: UUID) -> dict[str, Any]:
    """A 10 m profile covering the farm, as the real merge would produce."""
    from rasterio.transform import from_origin

    row = (
        (
            await session.execute(
                text(
                    f"SELECT ST_XMin(e) x0, ST_YMin(e) y0, ST_XMax(e) x1, ST_YMax(e) y1 "
                    f'FROM (SELECT ST_Envelope(boundary_utm) e FROM "{schema}".farms '
                    "WHERE id = :id) s"
                ),
                {"id": farm_id},
            )
        )
        .mappings()
        .one()
    )
    res = 10.0
    width = max(1, int((row["x1"] - row["x0"]) / res) + 1)
    height = max(1, int((row["y1"] - row["y0"]) / res) + 1)
    return {
        "transform": from_origin(row["x0"], row["y1"], res, res),
        "width": width,
        "height": height,
    }


async def _set_up_farm_subscription(
    admin_session: AsyncSession,
    *,
    slug: str,
    fetch_farm_aoi: bool,
) -> tuple[UUID, UUID, str]:
    """Tenant + farm + block + one farm-level subscription.

    Returns ``(subscription_id, farm_id, tenant_schema)``.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, _block_id = await _create_farm_and_block(client)
        product_id = await _get_s2l2a_product_id(admin_session)

    sub_id = uuid4()
    # No API for farm subscriptions yet — 0074 populated them by collapsing
    # the per-block rows, and the switch is set by an operator.
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant.schema_name}".imagery_farm_subscriptions '
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, :fetch)"
        ),
        {
            "id": sub_id,
            "farm": UUID(farm_id),
            "product": UUID(product_id),
            "fetch": fetch_farm_aoi,
        },
    )
    await admin_session.commit()
    return sub_id, UUID(farm_id), tenant.schema_name


@pytest.mark.asyncio
async def test_a_farm_without_the_switch_is_never_swept(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id, _farm_id, schema = await _set_up_farm_subscription(
        admin_session, slug="farm-aoi-off", fetch_farm_aoi=False
    )
    imagery_tasks.set_provider_factory(lambda _code: _FakeProvider((SCENE,)))
    try:
        due = await _due_subscription_ids(admin_session, schema)
        assert sub_id not in due

        # And calling discovery directly still refuses, because the switch can
        # be turned off between the sweep and the task running.
        result = await imagery_tasks._discover_farm_scenes_async(sub_id, schema)
        assert result == {"discovered": 0, "queued": 0, "skipped_cloud": 0}
        assert await _farm_job_count(admin_session, schema) == 0
    finally:
        imagery_tasks.reset_provider_factory()


async def _due_subscription_ids(session: AsyncSession, schema: str) -> set[UUID]:
    rows = (
        await session.execute(
            text(
                f'SELECT id FROM "{schema}".imagery_farm_subscriptions '
                "WHERE is_active AND fetch_farm_aoi AND deleted_at IS NULL"
            )
        )
    ).all()
    return {UUID(str(r[0])) for r in rows}


async def _farm_job_count(session: AsyncSession, schema: str) -> int:
    return int(
        (
            await session.execute(
                text(f'SELECT count(*) FROM "{schema}".imagery_farm_ingestion_jobs')
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_discovery_is_idempotent_on_the_same_scene(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id, _farm_id, schema = await _set_up_farm_subscription(
        admin_session, slug="farm-aoi-idem", fetch_farm_aoi=True
    )
    imagery_tasks.set_provider_factory(lambda _code: _FakeProvider((SCENE,)))
    from app.modules.imagery.tasks import acquire_farm_scene

    monkeypatch.setattr(acquire_farm_scene, "delay", lambda *a, **k: None)
    try:
        first = await imagery_tasks._discover_farm_scenes_async(sub_id, schema)
        assert first["queued"] == 1
        assert await _farm_job_count(admin_session, schema) == 1

        second = await imagery_tasks._discover_farm_scenes_async(sub_id, schema)
        assert second["queued"] == 0
        assert await _farm_job_count(admin_session, schema) == 1
    finally:
        imagery_tasks.reset_provider_factory()


@pytest.mark.asyncio
async def test_an_acquired_pass_is_recorded_as_fetched_under_the_farm_hash(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id, farm_id, schema = await _set_up_farm_subscription(
        admin_session, slug="farm-aoi-acquire", fetch_farm_aoi=True
    )
    provider = _FakeProvider((SCENE,))
    imagery_tasks.set_provider_factory(lambda _code: provider)
    capture = _CaptureStorage()
    monkeypatch.setattr(imagery_tasks, "_get_storage", lambda: capture)
    seen_hashes = _stub_rasterio(monkeypatch)

    from app.modules.imagery.tasks import acquire_farm_scene

    monkeypatch.setattr(acquire_farm_scene, "delay", lambda *a, **k: None)
    try:
        await imagery_tasks._discover_farm_scenes_async(sub_id, schema)
        job_id = UUID(
            str(
                (
                    await admin_session.execute(
                        text(f'SELECT id FROM "{schema}".imagery_farm_ingestion_jobs')
                    )
                ).scalar_one()
            )
        )

        result = await imagery_tasks._acquire_farm_scene_async(job_id, schema)
        assert result["status"] == "succeeded"

        farm_hash = (
            await admin_session.execute(
                text(f'SELECT aoi_hash FROM "{schema}".farms WHERE id = :id'),
                {"id": farm_id},
            )
        ).scalar_one()

        # The raster is written under the FARM's hash, which is what makes it a
        # different object from any of its blocks'.
        assert seen_hashes == [farm_hash]
        assert capture.uploads, "raw bands were never written"
        assert farm_hash in capture.uploads[0][0]

        # The fetch asked for the farm boundary, not a block's.
        assert len(provider.fetched_aois) == 1

        row = (
            (
                await admin_session.execute(
                    text(
                        f'SELECT source, blocks_merged, aoi_hash FROM "{schema}".'
                        "farm_scene_rasters WHERE farm_id = :f"
                    ),
                    {"f": farm_id},
                )
            )
            .mappings()
            .one()
        )
        assert row["source"] == "fetched"
        # Nothing was merged; 0 would read as "merged nothing" rather than
        # "the question does not apply".
        assert row["blocks_merged"] is None
        assert row["aoi_hash"] == farm_hash

        # The indices column holds CODES; assets_written holds object PATHS.
        # The first live fetch recorded ["…/raw_bands.tif", "ndvi", "ndmi"] —
        # one real key and two labels — because both read the same dict.
        job_row = (
            (
                await admin_session.execute(
                    text(
                        f'SELECT assets_written FROM "{schema}".'
                        "imagery_farm_ingestion_jobs WHERE id = :i"
                    ),
                    {"i": job_id},
                )
            )
            .mappings()
            .one()
        )
        assets = job_row["assets_written"]
        assert len(assets) == 3, assets
        assert all("/" in a and a.endswith(".tif") for a in assets), assets

        status = (
            await admin_session.execute(
                text(f'SELECT status FROM "{schema}".imagery_farm_ingestion_jobs WHERE id = :i'),
                {"i": job_id},
            )
        ).scalar_one()
        assert status == "succeeded"
    finally:
        imagery_tasks.reset_provider_factory()


@pytest.mark.asyncio
async def test_a_stitch_never_overwrites_a_fetched_surface(
    admin_session: AsyncSession,
) -> None:
    """The fetched surface covers ground no block was drawn around.

    Letting a later stitch replace it would silently shrink the farm back to
    its blocks — the exact hole this whole path exists to close.
    """
    _sub_id, farm_id, schema = await _set_up_farm_subscription(
        admin_session, slug="farm-aoi-precedence", fetch_farm_aoi=True
    )
    product_id = UUID(await _get_s2l2a_product_id(admin_session))
    at = datetime(2026, 3, 1, 8, 30, tzinfo=UTC)
    farm_hash = (
        await admin_session.execute(
            text(f'SELECT aoi_hash FROM "{schema}".farms WHERE id = :id'), {"id": farm_id}
        )
    ).scalar_one()

    from app.modules.imagery.repository import ImageryRepository

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    repo = ImageryRepository(admin_session)
    await repo.record_farm_scene_raster(
        farm_id=farm_id,
        product_id=product_id,
        scene_datetime=at,
        scene_id="SCENE_A",
        stac_item_id="sentinel_hub/s2_l2a/SCENE_A/" + farm_hash,
        aoi_hash=farm_hash,
        blocks_merged=None,
        indices=["ndvi"],
        source="fetched",
    )
    await repo.record_farm_scene_raster(
        farm_id=farm_id,
        product_id=product_id,
        scene_datetime=at,
        scene_id="SCENE_A",
        stac_item_id="sentinel_hub/s2_l2a/SCENE_A/" + farm_hash,
        aoi_hash=farm_hash,
        blocks_merged=36,
        indices=["ndvi"],
        source="stitched",
    )
    await admin_session.commit()

    row = (
        (
            await admin_session.execute(
                text(
                    f'SELECT source, blocks_merged FROM "{schema}".farm_scene_rasters '
                    "WHERE farm_id = :f"
                ),
                {"f": farm_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["source"] == "fetched"
    assert row["blocks_merged"] is None


@pytest.mark.asyncio
async def test_a_farm_fetch_writes_the_block_numbers(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The keystone of letting the per-block FETCH stop.

    Every index number in the product — Insights, alerts, recommendations,
    baselines — reads block_index_aggregates. If a farm-AOI fetch did not
    write those, switching a farm over would leave the map looking right
    while every figure beside it quietly stopped moving.
    """
    sub_id, farm_id, schema = await _set_up_farm_subscription(
        admin_session, slug="farm-aoi-aggs", fetch_farm_aoi=True
    )
    grid = await _farm_grid(admin_session, schema, farm_id)
    imagery_tasks.set_provider_factory(lambda _code: _FakeProvider((SCENE,)))
    monkeypatch.setattr(imagery_tasks, "_get_storage", lambda: _CaptureStorage())
    _stub_rasterio(monkeypatch, grid=grid, index_value=0.5)

    from app.modules.imagery.tasks import acquire_farm_scene

    monkeypatch.setattr(acquire_farm_scene, "delay", lambda *a, **k: None)
    try:
        await imagery_tasks._discover_farm_scenes_async(sub_id, schema)
        job_id = UUID(
            str(
                (
                    await admin_session.execute(
                        text(f'SELECT id FROM "{schema}".imagery_farm_ingestion_jobs')
                    )
                ).scalar_one()
            )
        )
        result = await imagery_tasks._acquire_farm_scene_async(job_id, schema)
        assert result["status"] == "succeeded", result

        rows = (
            (
                await admin_session.execute(
                    text(
                        f'SELECT index_code, mean, stac_item_id FROM "{schema}".'
                        "block_index_aggregates ORDER BY index_code"
                    )
                )
            )
            .mappings()
            .all()
        )
        # One row per block per index — the farm has one block in this fixture.
        assert {r["index_code"] for r in rows} == {"ndvi", "ndmi"}
        assert result["block_aggregates"] == len(rows) == 2
        # The constant surface means the block mean IS that constant; anything
        # else would mean the block mask selected the wrong pixels.
        assert all(abs(float(r["mean"]) - 0.5) < 1e-6 for r in rows), rows
        # Traceable to the surface the number came from, not to a per-block
        # object that no longer exists.
        farm_hash = await _farm_hash(admin_session, schema, farm_id)
        assert all(r["stac_item_id"].endswith(farm_hash) for r in rows)
    finally:
        imagery_tasks.reset_provider_factory()


async def _farm_hash(session: AsyncSession, schema: str, farm_id: UUID) -> str:
    return str(
        (
            await session.execute(
                text(f'SELECT aoi_hash FROM "{schema}".farms WHERE id = :id'), {"id": farm_id}
            )
        ).scalar_one()
    )
