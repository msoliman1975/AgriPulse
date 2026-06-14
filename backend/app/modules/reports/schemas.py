"""Reports API schemas.

Shared pieces live here; each report's response model is added below the
`ReportPeriod` envelope as its PR lands. Decimals serialise to JSON
strings (Pydantic default) so the FE keeps full precision.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ReportPeriod(BaseModel):
    """The resolved [since, until] window a report covers.

    Echoed back on every report response so the FE can render the
    period header ("1 May - 31 May") without re-deriving the default
    window. `since`/`until` are always populated server-side even when
    the caller omits them (defaults to the last 30 days).
    """

    model_config = ConfigDict(from_attributes=True)

    since: datetime
    until: datetime


# --- PR-1: Seasonal Crop Health ---------------------------------------------

# Vegetation status derived from the baseline deviation (z-score) of the
# latest scene, so it works for any index (NDVI/NDRE/NDMI/...) rather than
# the NDVI-shaped health buckets. `unknown` = no z-score (no baseline yet).
CropHealthStatus = Literal["normal", "watch", "stressed", "unknown"]


class CropHealthBlockRow(BaseModel):
    """One block's vegetation summary over the report window.

    `baseline_z` is the latest scene's deviation from the block's
    historical baseline for that index/day-of-year (negative = below
    normal). `trend_pct` is the percentage change from the first to the
    last block-mean in the window. `p10/p50/p90` are the latest scene's
    *spatial* percentiles across the block (within-field uniformity).
    """

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    block_name: str
    crop_name_en: str | None = None
    crop_name_ar: str | None = None
    status: CropHealthStatus
    last_value: Decimal | None
    last_observed_at: datetime | None
    baseline_z: Decimal | None
    trend_pct: Decimal | None
    min_value: Decimal | None
    max_value: Decimal | None
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    avg_valid_pixel_pct: Decimal | None
    avg_cloud_pct: Decimal | None
    scene_count: int


class CropHealthSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_count: int
    with_data_count: int
    normal: int
    watch: int
    stressed: int
    unknown: int
    avg_last_value: Decimal | None


class CropHealthReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    index_code: str
    period: ReportPeriod
    blocks: list[CropHealthBlockRow]
    summary: CropHealthSummary


# --- PR-2: Field Variability / Zone Anomaly ---------------------------------

# Per-block grid outcome on the latest in-window scene.
#   anomalies   - reliable distribution, ≥1 low-outlier cell
#   clear       - reliable distribution, no outliers
#   insufficient- has a scene but too few cells / too uniform to judge
#   no_data     - grid configured but no scene in the window
#   no_grid     - no active grid configuration for the block
ZoneAnomalyStatus = Literal["anomalies", "clear", "insufficient", "no_data", "no_grid"]


class ZoneAnomalyBlockRow(BaseModel):
    """One block's within-field variability on its latest grid scene.

    `worst_z` is the most negative cell deviation (cell_mean - block_mean)
    / block_std — how far the weakest patch sits below the block. Cells
    at or below `-threshold_k` std-devs are flagged. `flagged_area_ha`
    is the combined area of those cells.
    """

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    block_name: str
    status: ZoneAnomalyStatus
    scene_time: datetime | None
    cell_count: int
    flagged_count: int
    flagged_area_ha: Decimal | None
    worst_z: Decimal | None
    block_mean: Decimal | None
    block_std: Decimal | None
    threshold_k: Decimal | None


class ZoneAnomalySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_count: int
    blocks_with_grid: int
    blocks_with_anomalies: int
    total_flagged_cells: int
    total_flagged_area_ha: Decimal | None


class ZoneAnomalyReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    index_code: str
    period: ReportPeriod
    blocks: list[ZoneAnomalyBlockRow]
    summary: ZoneAnomalySummary


# --- PR-3: Irrigation & Water Balance ---------------------------------------


class WaterBalanceWeather(BaseModel):
    """Farm-level weather context for the window: crop water demand (ET₀)
    against rainfall supply. Per-farm (weather is farm-grained), shown as
    the report header above the per-block irrigation table."""

    model_config = ConfigDict(from_attributes=True)

    days_with_data: int
    et0_mm_total: Decimal | None
    precip_mm_total: Decimal | None
    et0_mm_avg_daily: Decimal | None


class WaterBalanceBlockRow(BaseModel):
    """One block's irrigation activity over the window. `adherence_pct`
    is applied volume / recommended volume — how closely the operator
    followed the schedule."""

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    block_name: str
    scheduled_count: int
    applied_count: int
    skipped_count: int
    pending_count: int
    recommended_mm_total: Decimal | None
    applied_mm_total: Decimal | None
    adherence_pct: Decimal | None
    last_scheduled_for: date | None


class WaterBalanceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    block_count: int
    blocks_with_schedules: int
    recommended_mm_total: Decimal | None
    applied_mm_total: Decimal | None
    applied_count: int
    skipped_count: int
    pending_count: int


class WaterBalanceReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    period: ReportPeriod
    weather: WaterBalanceWeather
    blocks: list[WaterBalanceBlockRow]
    summary: WaterBalanceSummary


# --- PR-4: Weather & Growing-Degree-Days Summary ----------------------------


class WeatherSummaryStats(BaseModel):
    """Farm window roll-up. GDD is base-10°C (the stored derived series);
    crop-specific base temps are surfaced via `WeatherCropContext` for the
    reader to interpret against."""

    model_config = ConfigDict(from_attributes=True)

    days_with_data: int
    temp_min_c: Decimal | None
    temp_max_c: Decimal | None
    temp_mean_c: Decimal | None
    precip_mm_total: Decimal | None
    rain_days: int
    et0_mm_total: Decimal | None
    et0_mm_avg_daily: Decimal | None
    gdd_base10_total: Decimal | None
    gdd_cumulative_season: Decimal | None


class WeatherDailyPoint(BaseModel):
    """One day in the series the FE charts (temp band + GDD accumulation)."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    temp_min_c: Decimal | None
    temp_max_c: Decimal | None
    temp_mean_c: Decimal | None
    precip_mm: Decimal | None
    et0_mm: Decimal | None
    gdd_base10: Decimal | None
    gdd_cumulative_season: Decimal | None


class WeatherCropContext(BaseModel):
    """A crop currently on the farm + its agronomic constants, so the
    reader can judge the accumulated GDD against the expected season."""

    model_config = ConfigDict(from_attributes=True)

    crop_id: UUID
    name_en: str
    name_ar: str | None
    block_count: int
    gdd_base_temp_c: Decimal | None
    default_growing_season_days: int | None


class WeatherSummaryReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    period: ReportPeriod
    stats: WeatherSummaryStats
    daily: list[WeatherDailyPoint]
    crops: list[WeatherCropContext]


# --- PR-5: Farm Operations & Agronomy Log -----------------------------------

OpsLogKind = Literal["activity", "alert", "recommendation"]


class OpsLogEntry(BaseModel):
    """One row in the unified operations timeline. `kind` drives the FE
    icon/colour; `time` is the operational moment (activity scheduled
    date, or alert/recommendation creation time)."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    kind: OpsLogKind
    block_name: str | None
    title: str
    status: str | None = None
    severity: str | None = None
    detail: str | None = None


class OpsLogSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    activities_total: int
    activities_completed: int
    activities_skipped: int
    alerts_opened: int
    alerts_resolved: int
    recommendations_total: int
    recommendations_applied: int
    recommendations_dismissed: int


class OperationsLogReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    period: ReportPeriod
    entries: list[OpsLogEntry]
    summary: OpsLogSummary
