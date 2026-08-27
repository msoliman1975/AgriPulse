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

from pydantic import BaseModel, ConfigDict, Field


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


# --- Custom (tenant-defined) report columns ---------------------------------
#
# Crop attributes and custom signals are the two things a tenant defines for
# itself, and neither used to appear in any report. They share one envelope
# because a report renders them the same way — a column with a label, a unit
# and a typed cell — regardless of which of the two it came from. The
# resolution rules live in `custom_fields.py`.

# Which catalog a column came from. Also the first half of its `key`.
CustomFieldSource = Literal["crop_attribute", "signal"]


class CustomFieldOption(BaseModel):
    """One allowed value of a select-typed column.

    Carried on the definition rather than resolved into the cell so the FE can
    show the localised label for a stored code, and so a value whose option was
    since removed still renders as its raw code rather than vanishing.
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_ar: str | None = None


class CustomFieldDef(BaseModel):
    """One offerable column: what it is called, and how to render its cell.

    ``key`` is ``"{source}:{code}"`` — the single string the `fields` query
    param carries, the row dict is keyed by, and the FE uses as a column id.

    ``value_type`` is the source's own type name, not a normalised one:
    ``integer|decimal|text|boolean|date|single_select|multi_select`` for a crop
    attribute, ``numeric|categorical|event|boolean|geopoint`` for a signal.
    Normalising the two would lose exactly the distinctions the renderer needs
    (a `multi_select` is a chip list, a `date` is not a number).
    """

    model_config = ConfigDict(from_attributes=True)

    key: str
    source: CustomFieldSource
    code: str
    name_en: str
    # Signal definitions have no Arabic name column, so this is always None for
    # `source="signal"` and the FE falls back to `name_en`.
    name_ar: str | None = None
    value_type: str
    unit_en: str | None = None
    unit_ar: str | None = None
    decimal_places: int | None = None
    options: list[CustomFieldOption] | None = None


class CustomFieldValue(BaseModel):
    """One block's value for one custom column.

    Typed fields rather than a rendered string: the CSV export, the sort and
    any future threshold both need the number as a number. Exactly one
    ``value_*`` is populated for a given ``value_type``; a block with no value
    is simply absent from the row's `custom` map rather than present-and-empty.
    """

    model_config = ConfigDict(from_attributes=True)

    key: str
    source: CustomFieldSource
    code: str
    value_numeric: Decimal | None = None
    # A single-select's chosen option code lands here too, so the FE reads one
    # field for every scalar-string type.
    value_text: str | None = None
    value_boolean: bool | None = None
    value_date: date | None = None
    value_options: list[str] | None = None
    # Signals only: when the observation behind this cell was taken. A crop
    # attribute is as-of-now and carries None. The FE shows it so a stale
    # reading is visible as stale rather than as the block's current state.
    observed_at: datetime | None = None


class CustomFieldsResponse(BaseModel):
    """`GET /farms/{farm_id}/reports/custom-fields` — the column picker's menu."""

    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    fields: list[CustomFieldDef]


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
    block_name_ar: str | None = None
    crop_name_en: str | None = None
    crop_name_ar: str | None = None
    # Hierarchical taxonomy path of the block's current crop, e.g.
    # "mango.alphonso.short" / "cotton" (empty when none).
    crop_path: str | None = None
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
    # Tenant-defined columns the caller asked for, keyed by
    # `CustomFieldDef.key`. Absent key = no value on this block, which the
    # FE renders as an em dash rather than a zero.
    custom: dict[str, CustomFieldValue] = Field(default_factory=dict)


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
    farm_name_ar: str | None = None
    index_code: str
    period: ReportPeriod
    # Echoes the crop-taxonomy path prefix the report was filtered to
    # (None = whole farm), so the FE can render the active filter chip.
    crop_path: str | None = None
    blocks: list[CropHealthBlockRow]
    summary: CropHealthSummary
    # The custom columns this response actually carries, in picker order.
    # The FE renders its table from this rather than from the row keys, so
    # a column with no value on any block still shows (empty) instead of
    # silently disappearing.
    custom_fields: list[CustomFieldDef] = Field(default_factory=list)


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
    block_name_ar: str | None = None
    status: ZoneAnomalyStatus
    scene_time: datetime | None
    cell_count: int
    flagged_count: int
    flagged_area_ha: Decimal | None
    worst_z: Decimal | None
    block_mean: Decimal | None
    block_std: Decimal | None
    threshold_k: Decimal | None
    # Tenant-defined columns the caller asked for, keyed by
    # `CustomFieldDef.key`. Absent key = no value on this block, which the
    # FE renders as an em dash rather than a zero.
    custom: dict[str, CustomFieldValue] = Field(default_factory=dict)


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
    farm_name_ar: str | None = None
    index_code: str
    period: ReportPeriod
    blocks: list[ZoneAnomalyBlockRow]
    summary: ZoneAnomalySummary
    # The custom columns this response actually carries, in picker order.
    # The FE renders its table from this rather than from the row keys, so
    # a column with no value on any block still shows (empty) instead of
    # silently disappearing.
    custom_fields: list[CustomFieldDef] = Field(default_factory=list)


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
    block_name_ar: str | None = None
    scheduled_count: int
    applied_count: int
    skipped_count: int
    pending_count: int
    recommended_mm_total: Decimal | None
    applied_mm_total: Decimal | None
    adherence_pct: Decimal | None
    last_scheduled_for: date | None
    # Tenant-defined columns the caller asked for, keyed by
    # `CustomFieldDef.key`. Absent key = no value on this block, which the
    # FE renders as an em dash rather than a zero.
    custom: dict[str, CustomFieldValue] = Field(default_factory=dict)


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
    farm_name_ar: str | None = None
    period: ReportPeriod
    weather: WaterBalanceWeather
    blocks: list[WaterBalanceBlockRow]
    summary: WaterBalanceSummary
    # The custom columns this response actually carries, in picker order.
    # The FE renders its table from this rather than from the row keys, so
    # a column with no value on any block still shows (empty) instead of
    # silently disappearing.
    custom_fields: list[CustomFieldDef] = Field(default_factory=list)


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
    # Anomaly roll-up vs the day-of-year climatology baselines (PR-W6).
    # Counts days in the window whose first-class weather index ran >=2 sigma
    # from the seasonal normal — None when no baseline data covers the
    # window yet (climatology needs ≥3 samples/DOY). `days_with_anomaly`
    # is the denominator (days that had any z-score at all).
    days_with_anomaly: int | None = None
    heat_anomaly_days: int | None = None
    et0_anomaly_days: int | None = None


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
    # Z-scores vs the seasonal (day-of-year) climatology for the first-class
    # weather indices (PR-W6). None where no baseline covers that day yet
    # (or, for rainfall, where the arid-climate std is ~0 so no z is defined).
    temp_anomaly_z: Decimal | None = None
    precip_anomaly_z: Decimal | None = None
    et0_anomaly_z: Decimal | None = None


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
    farm_name_ar: str | None = None
    period: ReportPeriod
    # Echoes the crop-taxonomy path prefix the crop context was filtered to
    # (None = every current crop on the farm).
    crop_path: str | None = None
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
    block_name_ar: str | None = None
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
    farm_name_ar: str | None = None
    period: ReportPeriod
    entries: list[OpsLogEntry]
    summary: OpsLogSummary


# --- PR-R5: Disease & Pest Pressure ----------------------------------------

# One row per (block, pathogen) with at least one scored day in the window.
RiskLevel = Literal["low", "moderate", "high"]


class WeatherRiskPressureRow(BaseModel):
    """One block's pressure for one pathogen over the window.

    Scores are the 0-100 ``weather_risk_daily.score``; ``days_high`` /
    ``days_moderate`` count days at that banding; ``latest_*`` is the most
    recent scored day so the FE can show the current state alongside the peak.
    """

    block_id: UUID
    block_name: str
    block_name_ar: str | None = None
    risk_code: str
    days_observed: int
    peak_score: int
    mean_score: int | None
    days_high: int
    days_moderate: int
    latest_level: RiskLevel
    latest_score: int
    latest_date: date
    # Tenant-defined columns the caller asked for, keyed by
    # `CustomFieldDef.key`. Absent key = no value on this block, which the
    # FE renders as an em dash rather than a zero.
    custom: dict[str, CustomFieldValue] = Field(default_factory=dict)


class WeatherRiskPressureSummary(BaseModel):
    """Farm-level roll-up across all (block, pathogen) rows in the window."""

    block_count: int
    pathogen_count: int
    blocks_at_risk: int
    total_high_days: int
    row_count: int


class WeatherRiskPressureReportResponse(BaseModel):
    farm_id: UUID
    farm_name: str
    farm_name_ar: str | None = None
    period: ReportPeriod
    rows: list[WeatherRiskPressureRow]
    summary: WeatherRiskPressureSummary
    # The custom columns this response actually carries, in picker order.
    # The FE renders its table from this rather than from the row keys, so
    # a column with no value on any block still shows (empty) instead of
    # silently disappearing.
    custom_fields: list[CustomFieldDef] = Field(default_factory=list)


# --- PR-R6: Signal Details --------------------------------------------------
#
# The one report whose rows are observations rather than blocks. Every other
# report collapses signals to one number per block; this one is for the
# question that collapse cannot answer — "show me every scouting reading that
# matched these filters, and who recorded it".


class SignalDetailFilters(BaseModel):
    """The filters the report actually ran with, echoed back.

    Not decoration. Unknown signal codes and block ids are dropped rather than
    rejected (same reasoning as `custom_fields.parse_field_refs`), so the FE
    has to be able to tell "I filtered to three signals" from "one of them no
    longer exists and you are looking at two".
    """

    model_config = ConfigDict(from_attributes=True)

    signal_codes: list[str] = Field(default_factory=list)
    block_ids: list[UUID] = Field(default_factory=list)
    categorical_values: list[str] = Field(default_factory=list)
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    recorded_by: UUID | None = None
    location_mode: str | None = None
    with_notes_only: bool = False
    with_attachment_only: bool = False


class SignalDetailRow(BaseModel):
    """One observation.

    The value lands in whichever `value_*` matches the definition's
    `value_kind`; the FE picks by `value_kind` rather than by probing for the
    non-null one, because `false` and `0` are real values.
    """

    model_config = ConfigDict(from_attributes=True)

    observation_id: UUID
    observed_at: datetime
    recorded_at: datetime
    signal_code: str
    signal_name: str
    signal_name_ar: str | None = None
    value_kind: str
    unit: str | None = None
    unit_ar: str | None = None
    # The definition's value list and its Arabic labels, matched by position.
    # Carried on the row because the stored reading is always the English
    # code, so the reader needs the pair to show an Arabic label for it.
    categorical_values: list[str] | None = None
    categorical_values_ar: list[str] | None = None
    value_numeric: Decimal | None = None
    value_categorical: str | None = None
    value_event: str | None = None
    value_boolean: bool | None = None
    block_id: UUID | None = None
    # None for a farm-level observation (`block_id IS NULL`), which is a real
    # shape here — unlike in a custom column, where it would be broadcast.
    block_name: str | None = None
    block_name_ar: str | None = None
    crop_path: str | None = None
    notes: str | None = None
    recorded_by: UUID
    recorded_by_name: str | None = None
    recorded_by_name_ar: str | None = None
    location_mode: str
    has_attachment: bool
    # Set when the row came in as part of a grouped template submission, so
    # the reader can see three readings were one visit rather than three.
    template_observation_id: UUID | None = None
    # Set when the row came from a CSV upload (CS-7).
    import_batch_id: UUID | None = None


class SignalDetailCategoryCount(BaseModel):
    """How often one categorical value occurred, for the per-signal breakdown."""

    model_config = ConfigDict(from_attributes=True)

    value: str
    count: int


class SignalDetailStat(BaseModel):
    """Per-signal roll-up over the filtered rows.

    Computed over the rows the filters selected, not over the whole window —
    a summary that ignored the filters would contradict the table under it.
    Numeric statistics are None for a non-numeric signal.
    """

    model_config = ConfigDict(from_attributes=True)

    signal_code: str
    signal_name: str
    signal_name_ar: str | None = None
    value_kind: str
    unit: str | None = None
    observation_count: int
    block_count: int
    recorder_count: int
    first_observed_at: datetime
    last_observed_at: datetime
    min_value: Decimal | None = None
    mean_value: Decimal | None = None
    max_value: Decimal | None = None
    # Top categorical values by count, most frequent first. Empty for a
    # numeric signal.
    categories: list[SignalDetailCategoryCount] = Field(default_factory=list)


class SignalDetailSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_count: int
    signal_count: int
    block_count: int
    recorder_count: int
    # True when the row cap cut the table short. The stats above are computed
    # over the returned rows, so a truncated report has to say so or its
    # averages read as the period's averages.
    truncated: bool


class SignalDetailsReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    farm_name_ar: str | None = None
    period: ReportPeriod
    filters: SignalDetailFilters
    rows: list[SignalDetailRow]
    stats: list[SignalDetailStat]
    summary: SignalDetailSummary
