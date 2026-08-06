"""Observer API — PlatformAdmin / PlatformSupport only.

Mounted at /api/v1/admin/observer. Every endpoint is gated on
`platform.observe_pipeline`, which is read-only and deliberately separate from
`platform.run_backfill`: seeing that a number is wrong must not imply the right
to spend the shared CDSE allowance recomputing it.

  GET /tenants                                  — tenant picker
  GET /tenants/{tenant_id}/farms                — farm picker + observability summary
  GET /tenants/{tenant_id}/farms/{farm_id}/products
  GET /tenants/{tenant_id}/overview             — L0 stage ribbon
  GET /tenants/{tenant_id}/histogram            — L0 scenes by date bucket
  GET /tenants/{tenant_id}/scenes               — L1 scene table
  GET /tenants/{tenant_id}/scenes/indices       — L1 expanded row (per-index stats)
  GET /tenants/{tenant_id}/scenes/{job_id}      — L2 scene detail
  GET /tenants/{tenant_id}/scenes/{job_id}/pixel        — L2 explain one pixel
  GET /tenants/{tenant_id}/scenes/{job_id}/pixel-budget — L2 pixel reconciliation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.observer.pixels import PixelOutsideRasterError
from app.modules.observer.repository import JOB_STATUSES
from app.modules.observer.service import (
    ObserverService,
    SceneNotFoundError,
    SceneRasterUnavailableError,
    TenantNotFoundError,
    WindowTooWideError,
    get_observer_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/observer", tags=["admin-observer"])

_CAP = "platform.observe_pipeline"


def _service(session: AsyncSession = Depends(get_admin_db_session)) -> ObserverService:
    return get_observer_service(session)


# --- schemas ---------------------------------------------------------------


class TenantOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    schema_name: str


class FarmOption(BaseModel):
    """Farm picker row.

    Carries enough to answer "is there anything to observe here" before the
    operator commits to a selection — a farm with no subscriptions and a farm
    with a broken pipeline both show zero scenes, and only these fields tell
    them apart.
    """

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str | None
    code: str | None
    block_count: int
    blocks_with_imagery_sub: int
    blocks_with_grid: int
    has_weather_sub: bool
    first_scene_at: datetime | None
    last_scene_at: datetime | None


class ProductOption(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str
    resolution_m: float
    bands: list[str]
    supported_indices: list[str]
    provider_code: str
    provider_name: str


class Stage(BaseModel):
    key: str
    label: str
    count: int
    # None where no denominator is meaningful (the first stage has no
    # predecessor; consumers are not a conversion of scenes).
    expected: int | None
    shortfall: int | None
    verdict: Literal["ok", "warn", "bad", "info", "not_applicable"]
    detail: dict[str, Any]


class OverviewResponse(BaseModel):
    farm_id: UUID
    block_count: int
    window_from: datetime
    window_to: datetime
    stages: list[Stage]
    calc_versions: list[dict[str, Any]]
    # True when the blocks in scope hold aggregates from more than one
    # product: `block_index_daily` has no product dimension, so trend
    # coverage cannot be attributed to the selected product alone.
    trend_product_ambiguous: bool
    # Consumers are counted by creation time in the window, not by proven
    # descent from these scenes. OBS-8 replaces this with real lineage.
    consumers_are_window_proxy: bool


class HistogramBucket(BaseModel):
    bucket: datetime
    computed: int
    acquired_only: int
    skipped: int
    failed: int
    pending: int
    total: int


class SceneRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    job_id: UUID
    block_id: UUID
    block_name: str | None
    block_code: str | None
    product_id: UUID
    scene_id: str
    scene_datetime: datetime
    status: str
    cloud_cover_pct: float | None
    valid_pixel_pct: float | None
    error_code: str | None
    error_message: str | None
    stac_item_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_s: float | None
    indices_written: int
    cells_written: int
    cells_expected: int
    gridded: bool


class IndexRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    index_code: str
    mean: float | None
    min: float | None
    max: float | None
    p10: float | None
    p50: float | None
    p90: float | None
    std_dev: float | None
    valid_pixel_count: int
    total_pixel_count: int
    valid_pixel_pct: float | None
    cloud_cover_pct: float | None
    baseline_deviation: float | None
    stac_item_id: str
    inserted_at: datetime


class GridSnapshot(BaseModel):
    """The grid that governed this scene's time — not today's grid."""

    grid_config_id: UUID
    cell_size_m: float
    utm_srid: int
    cell_count: int
    effective_from: datetime | None
    effective_to: datetime | None


class CalcRun(BaseModel):
    """One execution of compute_indices for this scene (tenant 0058)."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_id: UUID | None
    calc_version: str
    mask_ruleset: str
    trigger: str
    outcome: str
    error: str | None
    aoi_pixel_count: int | None
    masked_pixel_count: int | None
    cell_count: int | None
    grid_config_id: UUID | None
    band_order: list[str] | None
    per_index: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime


class SceneDetail(BaseModel):
    # /v1/config is tenant-scoped and an Observer user has no tenant, so the
    # tile-server origin and bucket travel with the scene that needs them.
    tile_server_base_url: str
    s3_bucket: str
    job_id: UUID
    block_id: UUID
    product_id: UUID
    block_code: str | None
    block_name: str | None
    farm_id: UUID
    scene_id: str
    scene_datetime: datetime
    status: str
    stac_item_id: str | None
    cloud_cover_pct: float | None
    valid_pixel_pct: float | None
    error_code: str | None
    error_message: str | None
    requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    provider_code: str
    provider_name: str
    product_code: str
    product_name: str
    resolution_m: float
    bands: list[str]
    supported_indices: list[str]
    aoi_hash: str
    boundary_geojson: dict[str, Any]
    area_m2: float
    raw_asset_key: str | None
    index_asset_keys: dict[str, str]
    mask_ruleset: str
    mask_classes: list[int]
    grid: GridSnapshot | None
    # Every recorded execution for this scene, newest first. Two entries with
    # different calc_versions means an aggregate row was overwritten by a
    # different build — which the upserted row itself cannot show.
    calc_runs: list[CalcRun]


class PixelIndexResult(BaseModel):
    """One index's arithmetic at one pixel.

    `value` is what this pixel contributed to the aggregate — null when it
    contributed nothing. `raw_value` is what the formula produced regardless,
    so a masked pixel can still show its number next to the reason it was
    thrown away.
    """

    value: float | None
    raw_value: float | None
    formula_text: str | None
    substituted: str | None
    excluded_reason: str | None


class PixelExplainResponse(BaseModel):
    job_id: UUID
    scene_id: str
    scene_datetime: datetime
    block_id: UUID
    raw_asset_key: str
    row: int
    col: int
    lon: float
    lat: float
    inside_aoi: bool
    band_values: dict[str, float | None]
    scl_value: int | None
    scl_label: str | None
    masked: bool
    mask_reason: str | None
    indices: dict[str, PixelIndexResult]
    # Index code → why it cannot be shown for this product, e.g. NDMI on a
    # 4-band product with no SWIR.
    unavailable_indices: dict[str, str]
    # False means the product ships no scene-classification band, so no cloud
    # masking happened and this scene's valid-pixel share is not comparable
    # to one from a product that does mask.
    masking_available: bool


class PixelBudgetResponse(BaseModel):
    job_id: UUID
    aoi_pixel_count: int
    masked_pixel_count: int
    per_index: dict[str, dict[str, int]]
    recomputed_live: bool


# --- shared query params ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scope:
    """The selection rail. Every drill endpoint takes the same tuple, and
    duplicating five parameters across four signatures is how they drift."""

    farm_id: UUID
    window_from: datetime
    window_to: datetime
    block_ids: list[UUID] | None
    product_id: UUID | None


def scope_params(
    farm_id: UUID = Query(description="Required — Observer is farm-scoped."),
    window_from: datetime = Query(alias="from"),
    window_to: datetime = Query(alias="to"),
    block_ids: list[UUID] | None = Query(default=None, alias="blocks"),
    product_id: UUID | None = Query(default=None, alias="product"),
) -> Scope:
    """Resolve the shared query params.

    A plain function, not a class-based dependency: this module carries
    `from __future__ import annotations`, which stringifies annotations, and
    FastAPI cannot resolve a nested `Annotated[...]` inside a stringized
    `__init__` signature — it raises PydanticUserError at request time, not
    at import, so every scoped route 500s while `/tenants` keeps working.
    """
    return Scope(
        farm_id=farm_id,
        window_from=window_from,
        window_to=window_to,
        block_ids=block_ids,
        product_id=product_id,
    )


# --- endpoints -------------------------------------------------------------


@router.get("/tenants", response_model=list[TenantOption])
async def list_tenants(
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_tenants()


@router.get("/tenants/{tenant_id}/farms", response_model=list[FarmOption])
async def list_farms(
    tenant_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_farms(await _schema(service, tenant_id))


@router.get(
    "/tenants/{tenant_id}/farms/{farm_id}/products",
    response_model=list[ProductOption],
)
async def list_products(
    tenant_id: UUID,
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_products(await _schema(service, tenant_id), farm_id)


@router.get("/tenants/{tenant_id}/overview", response_model=OverviewResponse)
async def overview(
    tenant_id: UUID,
    scope: Scope = Depends(scope_params),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    del context
    schema = await _schema(service, tenant_id)
    try:
        return await service.overview(
            tenant_schema=schema,
            farm_id=scope.farm_id,
            block_ids=scope.block_ids,
            product_id=scope.product_id,
            window_from=scope.window_from,
            window_to=scope.window_to,
        )
    except WindowTooWideError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/histogram", response_model=list[HistogramBucket])
async def histogram(
    tenant_id: UUID,
    scope: Scope = Depends(scope_params),
    bucket: Literal["day", "week", "month"] = Query(default="week"),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    schema = await _schema(service, tenant_id)
    try:
        return await service.histogram(
            tenant_schema=schema,
            farm_id=scope.farm_id,
            block_ids=scope.block_ids,
            product_id=scope.product_id,
            window_from=scope.window_from,
            window_to=scope.window_to,
            bucket=bucket,
        )
    except (WindowTooWideError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/scenes", response_model=list[SceneRow])
async def list_scenes(
    tenant_id: UUID,
    scope: Scope = Depends(scope_params),
    scene_status: Annotated[list[str] | None, Query(alias="status")] = None,
    max_valid_pct: Annotated[float | None, Query(ge=0, le=100)] = None,
    with_error: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    if scene_status:
        unknown = sorted(set(scene_status) - set(JOB_STATUSES))
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown job status: {', '.join(unknown)}",
            )
    schema = await _schema(service, tenant_id)
    try:
        return await service.list_scenes(
            tenant_schema=schema,
            farm_id=scope.farm_id,
            block_ids=scope.block_ids,
            product_id=scope.product_id,
            window_from=scope.window_from,
            window_to=scope.window_to,
            statuses=scene_status,
            max_valid_pct=max_valid_pct,
            with_error=with_error,
            limit=limit,
            offset=offset,
        )
    except (WindowTooWideError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/scenes/indices", response_model=list[IndexRow])
async def scene_indices(
    tenant_id: UUID,
    block_id: UUID,
    product_id: UUID,
    scene_time: datetime,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    """Per-index aggregates behind one scene — the expanded scene-table row."""
    del context
    return await service.scene_indices(
        tenant_schema=await _schema(service, tenant_id),
        block_id=block_id,
        product_id=product_id,
        scene_time=scene_time,
    )


# --- L2: scene detail + pixel explain ---------------------------------------


@router.get("/tenants/{tenant_id}/scenes/{job_id}", response_model=SceneDetail)
async def scene_detail(
    tenant_id: UUID,
    job_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Inputs, mask ruleset, resolved grid geometry and asset keys."""
    del context
    try:
        return await service.scene_detail(
            tenant_schema=await _schema(service, tenant_id), job_id=job_id
        )
    except SceneNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene not found") from exc


@router.get("/tenants/{tenant_id}/scenes/{job_id}/pixel", response_model=PixelExplainResponse)
async def explain_pixel(
    tenant_id: UUID,
    job_id: UUID,
    lon: float = Query(ge=-180, le=180),
    lat: float = Query(ge=-90, le=90),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Explain one pixel: bands in, mask verdict, formula, value out.

    One GDAL range read against the raw-bands COG, so this answers a click
    without a job queue.
    """
    del context
    try:
        return await service.explain_pixel(
            tenant_schema=await _schema(service, tenant_id),
            job_id=job_id,
            lon=lon,
            lat=lat,
        )
    except SceneNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene not found") from exc
    except SceneRasterUnavailableError as exc:
        # 409, not 404: the scene exists, it simply never produced a raster.
        # A 404 would send the operator looking for a missing row.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except PixelOutsideRasterError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/scenes/{job_id}/pixel-budget", response_model=PixelBudgetResponse)
async def pixel_budget(
    tenant_id: UUID,
    job_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Where this scene's pixels went: AOI → masked → no-data → valid.

    Recomputed from the COG on every call, because the database keeps only
    the valid and total counts and nothing that separates a cloud-masked
    pixel from a sensor gap. OBS-5 persists the split so this becomes a
    cheap read.
    """
    del context
    try:
        return await service.pixel_budget(
            tenant_schema=await _schema(service, tenant_id), job_id=job_id
        )
    except SceneNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene not found") from exc
    except SceneRasterUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- helpers ---------------------------------------------------------------


async def _schema(service: ObserverService, tenant_id: UUID) -> str:
    try:
        return await service.schema_for(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found or inactive") from exc
