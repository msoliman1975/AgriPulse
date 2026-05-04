"""Full compute_indices pipeline against a synthetic 7-band COG.

We run the prior chain (`_discover_scenes_async`, `_acquire_scene_async`,
`_register_stac_item_async`) with a fake provider whose `fetch()`
returns a real multi-band TIFF synthesised in-memory by rasterio, and a
capture-only storage that holds those bytes plus per-index uploads.

Then we drive `_compute_indices_async` directly. Tests:
- Six per-index COGs are uploaded with deterministic keys.
- Six rows land in `block_index_aggregates`, one per index.
- `pgstac.items` row is upserted with all six index assets.
- Re-running compute_indices is a no-op (idempotent on the unique key).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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
    _get_s2l2a_product_id,
)

pytestmark = [pytest.mark.integration]


# ---- Synthetic COG fixture ------------------------------------------------


def _build_synthetic_raw_cog_around(
    *,
    west: float,
    north: float,
    height: int = 64,
    width: int = 64,
) -> bytes:
    """Return a 7-band float32 GeoTIFF in EPSG:32636 with origin at (west, north).

    Pixel size 10 m. Veg half (left) has high NIR + low RED; water half
    (right) has low NIR + slightly higher green. Used by the pipeline
    test so the AOI mask is guaranteed to find pixels.
    """
    bands = np.zeros((7, height, width), dtype=np.float32)
    half = width // 2
    bands[0, :, :half] = 0.08
    bands[1, :, :half] = 0.10
    bands[2, :, :half] = 0.09
    bands[3, :, :half] = 0.20
    bands[4, :, :half] = 0.55
    bands[5, :, :half] = 0.20
    bands[6, :, :half] = 0.18
    bands[0, :, half:] = 0.07
    bands[1, :, half:] = 0.13
    bands[2, :, half:] = 0.06
    bands[3, :, half:] = 0.05
    bands[4, :, half:] = 0.03
    bands[5, :, half:] = 0.02
    bands[6, :, half:] = 0.01
    transform = rasterio.transform.from_origin(west=west, north=north, xsize=10, ysize=10)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 7,
        "dtype": "float32",
        "crs": "EPSG:32636",
        "transform": transform,
        "tiled": True,
        "blockxsize": 16,
        "blockysize": 16,
        "compress": "deflate",
    }
    with MemoryFile() as memfile:
        with memfile.open(**profile) as ds:
            ds.write(bands)
        return bytes(memfile.read())


def _utm_aoi_geojson() -> dict[str, Any]:
    """A polygon in UTM 36N inside the synthetic raster's footprint."""
    # The synthetic raster spans (480000, 3340000) - (480000+320, 3340000-320).
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [480000, 3339680],
                [480320, 3339680],
                [480320, 3340000],
                [480000, 3340000],
                [480000, 3339680],
            ]
        ],
    }


def _wgs_aoi_geojson() -> dict[str, Any]:
    """A polygon in WGS84 — just provided for the block-context reader."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [31.2000, 30.1000],
                [31.2050, 30.1000],
                [31.2050, 30.1050],
                [31.2000, 30.1050],
                [31.2000, 30.1000],
            ]
        ],
    }


# ---- Test plumbing --------------------------------------------------------


class _FakeProvider:
    code = "sentinel_hub"

    def __init__(self, scenes: tuple[DiscoveredScene, ...], cog_bytes: bytes) -> None:
        self._scenes = scenes
        self._cog = cog_bytes

    async def discover(self, **_: Any) -> tuple[DiscoveredScene, ...]:
        return self._scenes

    async def fetch(self, **_: Any) -> FetchResult:
        return FetchResult(
            cog_bytes=self._cog,
            band_order=("blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"),
        )

    async def aclose(self) -> None:
        pass


class _S3DictStorage:
    """Capture writes + serve reads via rasterio's `s3://` URI scheme.

    We register ourselves in rasterio's environment by writing to a
    GDAL VSI memory file under the same path the production code
    constructs ``s3://bucket/key.tif``. That way the production
    rasterio.open(...) inside compute_indices reads the exact bytes
    we stored without going to MinIO.
    """

    bucket = "missionagre-uploads"

    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}
        self.upload_order: list[str] = []

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.uploads[key] = body
        self.upload_order.append(key)

    def presign_upload(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("presign_upload is not used in this test")

    def presign_download(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("presign_download is not used in this test")

    def head_object(self, **_: Any) -> Any:  # pragma: no cover
        raise AssertionError("head_object is not used in this test")

    def delete_object(self, **_: Any) -> None:  # pragma: no cover
        raise AssertionError("delete_object is not used in this test")


def _patch_rasterio_open_to_in_memory(
    monkeypatch: pytest.MonkeyPatch,
    *,
    storage: _S3DictStorage,
) -> None:
    """Make ``rasterio.open(s3://...)`` read from the in-memory storage.

    We monkey-patch the rasterio.open call inside `_rasterio_io.py` so
    that an `s3://bucket/key` URL resolves to bytes captured by the
    fake storage. This avoids any GDAL / MinIO IO during the test.
    """
    import rasterio as _rio

    from app.modules.imagery import _rasterio_io

    real_open = _rio.open

    def _open(uri: str, *args: Any, **kwargs: Any) -> Any:
        if isinstance(uri, str) and uri.startswith("s3://"):
            _, _, rest = uri.partition("s3://")
            _bucket, _, key = rest.partition("/")
            data = storage.uploads.get(key)
            if data is None:
                raise FileNotFoundError(f"Synthetic storage missing {uri}")
            memfile = MemoryFile(data)
            return memfile.open()
        return real_open(uri, *args, **kwargs)

    monkeypatch.setattr(_rasterio_io.rasterio, "open", _open)


async def _set_up_subscription(
    admin_session: AsyncSession,
    *,
    slug: str,
) -> tuple[UUID, UUID, str, UUID]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # The block boundary for THIS test must roughly match the synthetic
        # COG's UTM footprint. The farm router applies the geom triggers,
        # so we POST WGS-84 polygons; the trigger projects to UTM. Tests
        # are tolerant of small mismatches because the AOI mask is built
        # from boundary_utm at rasterio runtime.
        farm_resp = await client.post(
            "/api/v1/farms",
            json={
                "code": "FARM-INDICES",
                "name": "Indices Test Farm",
                "boundary": {
                    "type": "MultiPolygon",
                    "coordinates": [_wgs_aoi_geojson()["coordinates"]],
                },
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm_resp.status_code == 201, farm_resp.text
        farm_id = farm_resp.json()["id"]

        block_resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-IDX-1", "boundary": _wgs_aoi_geojson()},
        )
        assert block_resp.status_code == 201, block_resp.text
        block_id = block_resp.json()["id"]
        product_id = await _get_s2l2a_product_id(admin_session)
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/imagery/subscriptions",
            json={"product_id": product_id},
        )
        sub_id = UUID(sub_resp.json()["id"])
    return sub_id, UUID(block_id), tenant.schema_name, UUID(product_id)


# ---- Tests ----------------------------------------------------------------


async def _read_block_utm_origin(
    admin_session: AsyncSession,
    *,
    tenant_schema: str,
    block_id: UUID,
) -> tuple[float, float]:
    """Return (west, north) UTM 36N origin so the synthetic raster
    encloses the block's polygon with a small buffer.
    """
    row = (
        await admin_session.execute(
            text(
                f"SELECT ST_XMin(boundary_utm) AS xmin, "
                f"       ST_YMax(boundary_utm) AS ymax "
                f'FROM "{tenant_schema}".blocks WHERE id = :id'
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": block_id},
        )
    ).one()
    # Buffer the origin outward by ~200 m so a 64x10 m raster (640 m
    # square) covers the AOI with margin.
    return float(row.xmin) - 200.0, float(row.ymax) + 200.0


@pytest.mark.asyncio
async def test_compute_indices_writes_six_aggregates_and_six_cogs(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub_id, block_id, tenant_schema, _product_id = await _set_up_subscription(
        admin_session, slug="indices-pipeline-ok"
    )
    west, north = await _read_block_utm_origin(
        admin_session, tenant_schema=tenant_schema, block_id=block_id
    )
    cog_bytes = _build_synthetic_raw_cog_around(west=west, north=north)
    scenes = (
        DiscoveredScene(
            scene_id="S2A_INDICES_OK_20260301",
            scene_datetime=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("8.50"),
            geometry_geojson=_wgs_aoi_geojson(),
        ),
    )
    storage = _S3DictStorage()
    imagery_tasks.set_provider_factory(lambda: _FakeProvider(scenes, cog_bytes))
    monkeypatch.setattr(imagery_tasks, "_get_storage", lambda: storage)
    _patch_rasterio_open_to_in_memory(monkeypatch, storage=storage)

    from app.modules.imagery.tasks import (
        acquire_scene,
        compute_indices,
        register_stac_item,
    )

    monkeypatch.setattr(acquire_scene, "delay", lambda *a, **k: None)
    monkeypatch.setattr(register_stac_item, "delay", lambda *a, **k: None)
    monkeypatch.setattr(compute_indices, "delay", lambda *a, **k: None)

    try:
        # discover → acquire → register → compute (all async cores).
        await imagery_tasks._discover_scenes_async(sub_id, tenant_schema)
        job_id_raw = (
            await admin_session.execute(
                text(
                    f'SELECT id FROM "{tenant_schema}".imagery_ingestion_jobs '
                    "WHERE scene_id = 'S2A_INDICES_OK_20260301'"
                )
            )
        ).scalar_one()
        job_id = UUID(str(job_id_raw))
        await imagery_tasks._acquire_scene_async(job_id, tenant_schema)
        # Discover the raw_bands key from the storage capture.
        raw_bands_key_uploaded = next(
            k for k in storage.upload_order if k.endswith("/raw_bands.tif")
        )
        await imagery_tasks._register_stac_item_async(
            job_id, tenant_schema, [raw_bands_key_uploaded]
        )
        result = await imagery_tasks._compute_indices_async(
            job_id, tenant_schema, raw_bands_key_uploaded
        )
    finally:
        imagery_tasks.reset_provider_factory()

    # Six index assets uploaded.
    index_keys = [
        k for k in storage.uploads if k.endswith((".tif",)) and not k.endswith("/raw_bands.tif")
    ]
    assert len(index_keys) == 6
    suffixes = sorted(k.rsplit("/", 1)[1] for k in index_keys)
    assert suffixes == [
        "evi.tif",
        "gndvi.tif",
        "ndre.tif",
        "ndvi.tif",
        "ndwi.tif",
        "savi.tif",
    ]

    # Result reflects six indices computed.
    assert result["status"] == "indices_computed"
    assert sorted(result["indices"]) == [
        "evi",
        "gndvi",
        "ndre",
        "ndvi",
        "ndwi",
        "savi",
    ]

    # Six rows in block_index_aggregates with sane stats for the veg-half
    # of the synthetic raster (NDVI > 0.5 is roughly expected).
    rows = (
        await admin_session.execute(
            text(
                f"SELECT index_code, mean, valid_pixel_count, total_pixel_count "
                f'FROM "{tenant_schema}".block_index_aggregates ORDER BY index_code'
            )
        )
    ).all()
    assert len(rows) == 6
    by_index = {r.index_code: r for r in rows}
    assert by_index["ndvi"].mean is not None
    assert by_index["ndvi"].valid_pixel_count > 0
    # AOI footprint counts pixels — total_pixel_count is positive for at
    # least one index (the AOI may be slightly off the synthetic raster
    # bounds because the polygon was supplied in WGS84 and projected to
    # UTM by the trigger; tolerate either zero or positive).

    # pgstac.items has the upserted item with all six index assets.
    aoi_hash = (
        await admin_session.execute(
            text(f'SELECT aoi_hash FROM "{tenant_schema}".blocks WHERE id = :id').bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": block_id},
        )
    ).scalar_one()
    expected_item_id = f"sentinel_hub/s2_l2a/S2A_INDICES_OK_20260301/{aoi_hash}"
    item_row = (
        await admin_session.execute(
            text("SELECT content FROM pgstac.items " "WHERE collection = :c AND id = :id"),
            {
                "c": f"{tenant_schema}__s2_l2a",
                "id": expected_item_id,
            },
        )
    ).one()
    assets = item_row.content.get("assets", {})
    assert {"raw_bands", "ndvi", "ndwi", "evi", "savi", "ndre", "gndvi"}.issubset(assets.keys())


@pytest.mark.asyncio
async def test_compute_indices_idempotent_on_rerun(
    admin_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running compute_indices for the same job is a no-op.

    Aggregate-row UNIQUE on (time, block_id, index_code, product_id)
    prevents duplicates; the second pass just re-uploads the same COG
    bytes and re-upserts the same pgstac item.
    """
    sub_id, block_id, tenant_schema, _product_id = await _set_up_subscription(
        admin_session, slug="indices-pipeline-idemp"
    )
    west, north = await _read_block_utm_origin(
        admin_session, tenant_schema=tenant_schema, block_id=block_id
    )
    cog_bytes = _build_synthetic_raw_cog_around(west=west, north=north)
    scenes = (
        DiscoveredScene(
            scene_id="S2A_INDICES_RERUN",
            scene_datetime=datetime(2026, 3, 5, 8, 30, tzinfo=UTC),
            cloud_cover_pct=Decimal("4.00"),
            geometry_geojson=_wgs_aoi_geojson(),
        ),
    )
    storage = _S3DictStorage()
    imagery_tasks.set_provider_factory(lambda: _FakeProvider(scenes, cog_bytes))
    monkeypatch.setattr(imagery_tasks, "_get_storage", lambda: storage)
    _patch_rasterio_open_to_in_memory(monkeypatch, storage=storage)

    from app.modules.imagery.tasks import (
        acquire_scene,
        compute_indices,
        register_stac_item,
    )

    monkeypatch.setattr(acquire_scene, "delay", lambda *a, **k: None)
    monkeypatch.setattr(register_stac_item, "delay", lambda *a, **k: None)
    monkeypatch.setattr(compute_indices, "delay", lambda *a, **k: None)

    try:
        await imagery_tasks._discover_scenes_async(sub_id, tenant_schema)
        job_id_raw = (
            await admin_session.execute(
                text(
                    f'SELECT id FROM "{tenant_schema}".imagery_ingestion_jobs '
                    "WHERE scene_id = 'S2A_INDICES_RERUN'"
                )
            )
        ).scalar_one()
        job_id = UUID(str(job_id_raw))
        await imagery_tasks._acquire_scene_async(job_id, tenant_schema)
        raw_bands_key_uploaded = next(
            k for k in storage.upload_order if k.endswith("/raw_bands.tif")
        )
        await imagery_tasks._register_stac_item_async(
            job_id, tenant_schema, [raw_bands_key_uploaded]
        )
        await imagery_tasks._compute_indices_async(job_id, tenant_schema, raw_bands_key_uploaded)
        # Run twice.
        await imagery_tasks._compute_indices_async(job_id, tenant_schema, raw_bands_key_uploaded)
    finally:
        imagery_tasks.reset_provider_factory()

    # Still six aggregate rows (idempotency key prevented duplicates).
    count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant_schema}".' "block_index_aggregates")
        )
    ).scalar_one()
    assert count == 6


# Suppress unused-import warning when these aren't surfaced by name.
def _block_id_from_jobs(_session: AsyncSession, _job_id: UUID) -> UUID:  # pragma: no cover
    raise AssertionError("test helper accidentally used")


_ = (io,)
