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
  GET /tenants/{tenant_id}/scenes/{job_id}/pixel-grid   — L2 map: pixel + cell footprints
  POST /tenants/{tenant_id}/scenes/{job_id}:verify     — L3 verify one scene (sync)
  POST /tenants/{tenant_id}/verify-runs                — L3 named multi-scene run
  GET  /tenants/{tenant_id}/verify-runs[/{id}[/results]]
  POST /tenants/{tenant_id}/verify-runs/{id}:cancel
  GET  /tenants/{tenant_id}/weather/overview           — weather ribbon + coverage
  GET  /tenants/{tenant_id}/weather/attempts|index-days|explain
  GET  /tenants/{tenant_id}/lineage                    — L4 what an index caused
  GET  /tenants/{tenant_id}/lineage/source             — L4 reverse: decision -> row
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from celery import current_app as celery_current_app
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.observer.pixels import PixelOutsideRasterError
from app.modules.observer.repository import JOB_STATUSES
from app.modules.observer.service import (
    CellNotFoundError,
    DecisionNotFoundError,
    IndexNotSupportedError,
    ObserverService,
    SceneNotFoundError,
    SceneRasterUnavailableError,
    TenantNotFoundError,
    WeatherDayNotFoundError,
    WindowTooWideError,
    get_observer_service,
)
from app.modules.observer.verify_store import VerifyRunConflictError
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
    """One execution of compute_indices for this scene (tenant 0059)."""

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


class VerificationRow(BaseModel):
    """One scene's verification result."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    run_id: UUID | None
    job_id: UUID | None
    block_id: UUID
    product_id: UUID
    scene_time: datetime
    scene_id: str
    # `fast` checks aggregation only — the index COG already has masking
    # baked in. Only `full` can catch a masking-rule change, so the mode
    # travels with the verdict rather than being inferred from it.
    mode: Literal["fast", "full"]
    verdict: Literal["match", "drift", "source_missing", "error"]
    per_index: dict[str, Any]
    # Which build produced the numbers being checked, when lineage knows.
    calc_version_stored: str | None
    error: str | None
    duration_ms: int | None
    created_at: datetime


class VerifyRunRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    farm_id: UUID
    block_ids: list[UUID] | None
    product_id: UUID | None
    window_from: datetime
    window_to: datetime
    mode: Literal["fast", "full"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: dict[str, Any]
    error: str | None
    created_by_email: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class VerifyRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    farm_id: UUID
    window_from: datetime
    window_to: datetime
    mode: Literal["fast", "full"] = "full"
    block_ids: list[UUID] | None = None
    product_id: UUID | None = None


class WeatherCoverageDay(BaseModel):
    day: date
    # Distinct hours with an observation, out of 24.
    hours: int
    has_derived: bool
    index_rows: int


class WeatherOverviewResponse(BaseModel):
    farm_id: UUID
    window_from: datetime
    window_to: datetime
    # False = the farm has no weather subscription at all, so every zero
    # below is "never configured" rather than "broken".
    subscribed: bool
    stages: list[Stage]
    coverage: list[WeatherCoverageDay]
    # Days that produced a derived row from fewer hours than the floor. The
    # number exists, reads as authoritative, and came from part of a day.
    thin_days: list[WeatherCoverageDay]
    coverage_floor_hours: int
    # The derivation applies no floor of its own — Observer only reports. Said
    # explicitly so `thin_days` is never read as "these were rejected".
    derivation_enforces_floor: bool


class WeatherAttemptRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    provider_code: str
    status: str
    rows_ingested: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    block_id: UUID


class WeatherIndexDayRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    date: date
    index_code: str
    value: float | None
    value_min: float | None
    value_max: float | None
    value_aux: dict[str, Any]
    baseline_deviation: float | None
    computed_at: datetime
    # How many hours this day's value was actually computed from.
    source_hours: int


class WeatherHourlyRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    time: datetime
    provider_code: str
    air_temp_c: float | None
    humidity_pct: float | None
    precipitation_mm: float | None
    wind_speed_m_s: float | None
    solar_radiation_w_m2: float | None
    et0_mm: float | None


class WeatherDayExplain(BaseModel):
    """The weather counterpart of the pixel inspector."""

    index: dict[str, Any]
    derived: dict[str, Any] | None
    hourly: list[WeatherHourlyRow]
    catalog: dict[str, Any] | None
    hours_present: int
    hours_expected: int
    # The qualifier that belongs next to every number here: a day built from a
    # third of its hours is not comparable to a full one.
    coverage_sufficient: bool


class LineageConsumer(BaseModel):
    """A decision that recorded reading this index."""

    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    cell_id: UUID | None
    severity: str | None
    status: str | None
    # Which snapshot key matched — `indices.ndmi.mean` vs `grid.ndmi.mean`
    # is the difference between a block-level and a per-cell decision.
    snapshot_key: str
    # The value the tree actually saw, frozen at decision time.
    observed_value: str | None
    tree_code: str | None = None
    tree_version: int | None = None
    action_type: str | None = None
    rule_code: str | None = None


class CellAnomaly(BaseModel):
    cell_id: UUID
    mean: float
    # Standard deviations *below* the block mean (positive = below).
    z: float
    threshold: float
    row_idx: int
    col_idx: int


class LineageResponse(BaseModel):
    block_id: UUID
    index_code: str
    window_from: datetime
    window_to: datetime
    recommendations: list[LineageConsumer]
    alerts: list[LineageConsumer]
    cell_anomalies: list[CellAnomaly]
    anomaly_threshold: float | None
    anomaly_threshold_source: str | None
    # These edges are stored in the decision's own snapshot, not inferred
    # from timestamps — unlike the overview's consumer count.
    exact: bool
    consumer_count: int


class DecisionSourceResponse(BaseModel):
    kind: Literal["recommendation", "alert"]
    decision_id: UUID
    block_id: UUID
    cell_id: UUID | None
    created_at: datetime
    source_code: str | None
    index_code: str
    # What the decision recorded reading, frozen at the time.
    observed_value: float | None
    source_row: dict[str, Any] | None
    # What that row holds now.
    current_value: float | None
    # None when either side is missing: "cannot tell" is not "agrees". False
    # means the row was recomputed after the decision was made.
    values_agree: bool | None


class PixelFeatureRow(BaseModel):
    row: int
    col: int
    # None when the pixel produced no usable number (cloud-masked, sensor gap,
    # or divide-by-zero in this index's formula).
    value: float | None
    masked: bool
    geometry: dict[str, Any]
    lon: float
    lat: float


class CellFeatureRow(BaseModel):
    cell_id: UUID
    row_idx: int
    col_idx: int
    geometry: dict[str, Any]
    area_m2: float | None
    # Null mean with a non-null count means the cell existed and the zonal
    # pass found nothing usable in it — different from no row at all.
    mean: float | None
    min: float | None
    max: float | None
    std_dev: float | None
    valid_pixel_count: int | None
    total_pixel_count: int | None


class PixelGridResponse(BaseModel):
    job_id: UUID
    block_id: UUID
    index_code: str
    scene_datetime: datetime
    resolution_m: float
    boundary_geojson: dict[str, Any]
    selected_cell_id: UUID | None
    pixels: list[PixelFeatureRow]
    cells: list[CellFeatureRow]
    aoi_pixel_count: int
    returned_pixel_count: int
    # True when the AOI holds more pixels than the cap; the map is showing a
    # prefix, not the whole block.
    truncated: bool
    # Recomputed from exactly the pixels returned, so the panel can show the
    # arithmetic instead of asserting it.
    recomputed_mean: float | None
    recomputed_valid: int
    stored_cell_mean: float | None
    stored_cell_valid: int | None
    block_mean: float | None
    block_valid: int | None
    block_total: int | None
    # Cells claim a pixel by its centre; the block AOI by footprint touch. The
    # per-cell counts therefore do not sum to the block count, by design.
    cell_membership: Literal["centre"]
    block_membership: Literal["footprint_touch"]


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


# --- L3: verify -------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/scenes/{job_id}:verify",
    response_model=VerificationRow,
)
async def verify_scene(
    tenant_id: UUID,
    job_id: UUID,
    mode: Literal["fast", "full"] = Query(default="full"),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Recompute one scene and diff it against the stored aggregates.

    Synchronous — one scene is one task and the operator is already looking at
    it. Writes only to `observer_verifications`; nothing in the pipeline's
    tables is touched, because a drift verdict is a signal to open the
    Backfill Console, not a licence to repair.
    """
    schema = await _schema(service, tenant_id)
    try:
        row = await service.verify_scene(tenant_schema=schema, job_id=job_id, mode=mode)
    except SceneNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene not found") from exc
    except SceneRasterUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await _audit_verify(
        tenant_schema=schema,
        context=context,
        event="platform.observer_verify_scene",
        subject_id=job_id,
        details={"job_id": str(job_id), "mode": mode, "verdict": row["verdict"]},
    )
    return row


@router.post(
    "/tenants/{tenant_id}/verify-runs",
    response_model=VerifyRunRow,
    status_code=status.HTTP_201_CREATED,
)
async def create_verify_run(
    tenant_id: UUID,
    body: VerifyRunRequest,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Queue a verification across many scenes.

    A year across a 36-block farm is roughly 2,500 recomputations, which is
    not a request/response. Named run, progress, cancel — the Backfill
    Console's model, for the same reasons.
    """
    schema = await _schema(service, tenant_id)
    try:
        run = await service.create_verify_run(
            tenant_schema=schema,
            farm_id=body.farm_id,
            block_ids=body.block_ids,
            product_id=body.product_id,
            window_from=body.window_from,
            window_to=body.window_to,
            mode=body.mode,
            created_by_email=getattr(context, "email", None),
        )
    except VerifyRunConflictError as exc:
        # One run per farm: a second would re-read the same COGs while the
        # first is still working.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A verification run is already in progress for this farm "
            f"(run {exc.existing['id']}). Wait for it to finish, or cancel it.",
        ) from exc
    except WindowTooWideError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Dispatched by name, so the API process never imports the worker's task
    # module — the same decoupling the backfill console uses.
    celery_current_app.send_task(
        "observer.run_verification",
        kwargs={"run_id": str(run["id"]), "tenant_schema": schema},
    )
    await _audit_verify(
        tenant_schema=schema,
        context=context,
        event="platform.observer_verify_started",
        subject_id=run["id"],
        details={
            "run_id": str(run["id"]),
            "farm_id": str(body.farm_id),
            "mode": body.mode,
            "window_from": body.window_from.isoformat(),
            "window_to": body.window_to.isoformat(),
        },
    )
    return run


@router.get("/tenants/{tenant_id}/verify-runs", response_model=list[VerifyRunRow])
async def list_verify_runs(
    tenant_id: UUID,
    farm_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_verify_runs(
        tenant_schema=await _schema(service, tenant_id), farm_id=farm_id, limit=limit
    )


@router.get("/tenants/{tenant_id}/verify-runs/{run_id}", response_model=VerifyRunRow)
async def get_verify_run(
    tenant_id: UUID,
    run_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    del context
    run = await service.get_verify_run(
        tenant_schema=await _schema(service, tenant_id), run_id=run_id
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "verify run not found")
    return run


@router.get(
    "/tenants/{tenant_id}/verify-runs/{run_id}/results",
    response_model=list[VerificationRow],
)
async def list_verify_results(
    tenant_id: UUID,
    run_id: UUID,
    verdict: Literal["match", "drift", "source_missing", "error"] | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    """A finished run is a browsable report; filtering to `drift` is the point."""
    del context
    return await service.list_verifications(
        tenant_schema=await _schema(service, tenant_id),
        run_id=run_id,
        verdict=verdict,
        limit=limit,
    )


@router.post("/tenants/{tenant_id}/verify-runs/{run_id}:cancel", response_model=VerifyRunRow)
async def cancel_verify_run(
    tenant_id: UUID,
    run_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Release a run that is still queued or running, freeing its farm.

    One run per farm is enforced by a partial unique index, so a run that
    never settles would hold that farm indefinitely. Distinguishes "no such
    run" from "already finished" because retrying helps in neither case but
    they mean very different things.
    """
    schema = await _schema(service, tenant_id)
    row = await service.cancel_verify_run(tenant_schema=schema, run_id=run_id)
    if row is not None:
        await _audit_verify(
            tenant_schema=schema,
            context=context,
            event="platform.observer_verify_cancelled",
            subject_id=run_id,
            details={"run_id": str(run_id)},
        )
        return row
    if await service.get_verify_run(tenant_schema=schema, run_id=run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "verify run not found")
    raise HTTPException(
        status.HTTP_409_CONFLICT, "This run has already finished; there is nothing to cancel."
    )


async def _audit_verify(
    *,
    tenant_schema: str,
    context: RequestContext,
    event: str,
    subject_id: UUID | None,
    details: dict[str, Any],
) -> None:
    """Audit a verification action.

    Verification is the only part of Observer that consumes worker time, so it
    is the only part that is audited. A drill-down view is indistinguishable
    from opening a farm page, and a row per pixel click would bury the events
    that matter.
    """
    from app.modules.observer.service import audit_observer_action

    await audit_observer_action(
        tenant_id=UUID(int=0),
        tenant_schema=tenant_schema,
        actor_user_id=getattr(context, "user_id", None),
        event_type=event,
        subject_id=subject_id,
        details=details,
    )


# --- weather lane -----------------------------------------------------------


@router.get("/tenants/{tenant_id}/weather/overview", response_model=WeatherOverviewResponse)
async def weather_overview(
    tenant_id: UUID,
    farm_id: UUID = Query(description="Weather is farm-scoped; blocks do not apply."),
    window_from: datetime = Query(alias="from"),
    window_to: datetime = Query(alias="to"),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """The weather ribbon plus per-day hour coverage.

    No `blocks` parameter: weather is measured at one farm centroid, and
    accepting a block filter that changed nothing would be worse than not
    offering one.
    """
    del context
    try:
        return await service.weather_overview(
            tenant_schema=await _schema(service, tenant_id),
            farm_id=farm_id,
            window_from=window_from,
            window_to=window_to,
        )
    except (WindowTooWideError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/weather/attempts", response_model=list[WeatherAttemptRow])
async def weather_attempts(
    tenant_id: UUID,
    farm_id: UUID,
    window_from: datetime = Query(alias="from"),
    window_to: datetime = Query(alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    """Fetch attempts — the weather lane's scene table."""
    del context
    try:
        return await service.weather_attempts(
            tenant_schema=await _schema(service, tenant_id),
            farm_id=farm_id,
            window_from=window_from,
            window_to=window_to,
            limit=limit,
        )
    except (WindowTooWideError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/weather/index-days", response_model=list[WeatherIndexDayRow])
async def weather_index_days(
    tenant_id: UUID,
    farm_id: UUID,
    index_code: str,
    window_from: datetime = Query(alias="from"),
    window_to: datetime = Query(alias="to"),
    limit: int = Query(default=200, ge=1, le=1000),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    try:
        return await service.weather_index_days(
            tenant_schema=await _schema(service, tenant_id),
            farm_id=farm_id,
            index_code=index_code,
            window_from=window_from,
            window_to=window_to,
            limit=limit,
        )
    except (WindowTooWideError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/weather/explain", response_model=WeatherDayExplain)
async def explain_weather_day(
    tenant_id: UUID,
    farm_id: UUID,
    index_code: str,
    day: date,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Everything that produced one daily index value.

    The hourly rows that fed it, the derived-daily intermediate, the catalog
    definition, and the coverage that qualifies all three.
    """
    del context
    try:
        return await service.explain_weather_day(
            tenant_schema=await _schema(service, tenant_id),
            farm_id=farm_id,
            index_code=index_code,
            day=day,
        )
    except WeatherDayNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no weather index row for {exc}") from exc


# --- L4: forward lineage ----------------------------------------------------


@router.get("/tenants/{tenant_id}/lineage", response_model=LineageResponse)
async def index_lineage(
    tenant_id: UUID,
    block_id: UUID,
    index_code: str,
    window_from: datetime = Query(alias="from"),
    window_to: datetime = Query(alias="to"),
    product_id: UUID | None = Query(default=None, alias="product"),
    scene_time: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """What this index produced: alerts, recommendations, cell anomalies.

    Exact rather than time-proximate — every consumer listed recorded reading
    this index in its evaluation snapshot, and comes back with the value it
    saw. Pass `scene_time` and `product` to include the per-cell anomaly pass
    for that scene.
    """
    del context
    try:
        return await service.index_lineage(
            tenant_schema=await _schema(service, tenant_id),
            block_id=block_id,
            product_id=product_id,
            index_code=index_code,
            window_from=window_from,
            window_to=window_to,
            scene_time=scene_time,
            limit=limit,
        )
    except (WindowTooWideError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/tenants/{tenant_id}/lineage/source", response_model=DecisionSourceResponse)
async def decision_source(
    tenant_id: UUID,
    kind: Literal["recommendation", "alert"],
    decision_id: UUID,
    index_code: str,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Reverse lineage: from a decision back to the row it read.

    `values_agree = false` means the aggregate was recomputed after the
    decision was made, so the recommendation is standing on a number that no
    longer exists.
    """
    del context
    try:
        return await service.decision_source(
            tenant_schema=await _schema(service, tenant_id),
            kind=kind,
            decision_id=decision_id,
            index_code=index_code,
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decision not found") from exc


@router.get("/tenants/{tenant_id}/scenes/{job_id}/pixel-grid", response_model=PixelGridResponse)
async def pixel_grid(
    tenant_id: UUID,
    job_id: UUID,
    index_code: str = Query(default="ndvi"),
    cell_id: UUID | None = Query(default=None),
    max_pixels: int = Query(default=4000, ge=1, le=20000),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: ObserverService = Depends(_service),
) -> dict[str, Any]:
    """Pixel and cell footprints for one scene, with the aggregates they feed.

    Drives the scene-detail map: every pixel as a polygon with its value,
    every grid cell with its stored aggregate, and the block value they roll
    up into. Pass `cell_id` to narrow to one cell — the pixels returned are
    then exactly the pixels that cell's stored mean was computed from, because
    the same `all_touched=False` centre rule is applied.
    """
    del context
    try:
        return await service.pixel_grid(
            tenant_schema=await _schema(service, tenant_id),
            job_id=job_id,
            index_code=index_code,
            cell_id=cell_id,
            max_pixels=max_pixels,
        )
    except SceneNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene not found") from exc
    except CellNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "cell not found") from exc
    except IndexNotSupportedError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{exc} is not supported by this scene's product",
        ) from exc
    except SceneRasterUnavailableError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- helpers ---------------------------------------------------------------


async def _schema(service: ObserverService, tenant_id: UUID) -> str:
    try:
        return await service.schema_for(tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tenant not found or inactive") from exc
