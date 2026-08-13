"""Pydantic schemas for the weather module's REST surface.

snake_case JSON, RFC 3339 timestamps, units called out in the column
(°C, mm, m/s, etc.) per ARCHITECTURE.md § 8.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubscriptionCreate(BaseModel):
    """POST /api/v1/blocks/{block_id}/weather/subscriptions body."""

    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Must match an active row in public.weather_providers.",
    )
    cadence_hours: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Per-subscription override of the tenant default cadence. "
            "NULL = use settings.weather_default_cadence_hours."
        ),
    )


class SubscriptionRead(BaseModel):
    """GET /api/v1/blocks/{block_id}/weather/subscriptions list item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    provider_code: str
    cadence_hours: int | None
    is_active: bool
    last_successful_ingest_at: datetime | None
    last_attempted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FarmSubscriptionCreate(BaseModel):
    """POST /api/v1/farms/{farm_id}/weather/subscriptions body."""

    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(..., min_length=1, max_length=64)
    cadence_hours: int | None = Field(default=None, ge=1)


class FarmSubscriptionUpdate(BaseModel):
    """PATCH body. Omitted fields are left alone."""

    model_config = ConfigDict(extra="forbid")

    cadence_hours: int | None = Field(default=None, ge=1)
    is_active: bool | None = None


class FarmSubscriptionRead(BaseModel):
    """One farm-level weather subscription.

    The farm is the unit weather is actually fetched for — one centroid, one
    provider call — so this is the subscription that matches the data.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    provider_code: str
    cadence_hours: int | None
    is_active: bool
    last_successful_ingest_at: datetime | None
    last_attempted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WeatherProviderRead(BaseModel):
    """One row of `public.weather_providers` — catalog of active providers.

    Surfaced via `GET /api/v1/weather/providers` so the SPA can populate
    provider pickers (e.g. the subscriptions template editor) without
    hard-coding the list against the DB.
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    kind: str


class WeatherIndexCatalogEntry(BaseModel):
    """One row of `public.weather_indices_catalog`.

    Surfaced via `GET /api/v1/weather/indices/catalog` so the SPA can
    build the weather-index picker + "why this matters" tooltips from
    DB-curated EN/AR metadata rather than hard-coding the list.
    """

    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_ar: str | None
    unit: str
    description_en: str | None
    description_ar: str | None
    value_min: Decimal | None
    value_max: Decimal | None
    source_kind: str
    default_visible: bool
    sort_order: int
    relation_indices_en: str | None
    relation_indices_ar: str | None
    relation_disease_en: str | None
    relation_disease_ar: str | None
    relation_insect_en: str | None
    relation_insect_ar: str | None


class WeatherIndexTimeseriesPoint(BaseModel):
    """One day of a weather-index series + its climatology context.

    ``zscore`` is the stored ``baseline_deviation``; ``baseline_mean`` /
    ``baseline_std`` come from the matching day-of-year baseline so the
    SPA can draw the climatology band. All nullable — a gap day or a DOY
    without a baseline yet leaves them None.

    ``is_forecast`` marks the points past today, projected from the
    provider's forecast rather than observed. The series carries both in
    one date-ascending list; the flag is what lets the chart draw the
    forward segment as a prediction instead of passing it off as measured.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date_type
    value: Decimal | None
    value_min: Decimal | None
    value_max: Decimal | None
    value_aux: dict[str, Any]
    zscore: Decimal | None
    baseline_mean: Decimal | None
    baseline_std: Decimal | None
    is_forecast: bool = False


class WeatherIndexTimeseriesResponse(BaseModel):
    farm_id: UUID
    index_code: str
    points: list[WeatherIndexTimeseriesPoint]


class WeatherIndexSummaryEntry(BaseModel):
    """Latest value + anomaly + 7-day trend for one weather index."""

    index_code: str
    latest_date: date_type
    value: Decimal | None
    zscore: Decimal | None
    trend_7d_delta: Decimal | None


class WeatherIndexSummaryResponse(BaseModel):
    farm_id: UUID
    as_of: datetime
    indices: list[WeatherIndexSummaryEntry]


class WeatherRiskTimeseriesPoint(BaseModel):
    """One day's disease/pest risk score for a block + pathogen.

    ``inputs`` is the favourable-condition accumulation that produced the
    score (the "why"), Decimals serialised as strings.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date_type
    risk_code: str
    score: int
    level: str
    inputs: dict[str, Any]


class WeatherRiskTimeseriesResponse(BaseModel):
    farm_id: UUID
    block_id: UUID
    risk_code: str
    points: list[WeatherRiskTimeseriesPoint]


class WeatherRiskSummaryEntry(BaseModel):
    """Latest risk score for one block + pathogen — drives the map overlay."""

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    risk_code: str
    date: date_type
    score: int
    level: str


class WeatherRiskSummaryResponse(BaseModel):
    farm_id: UUID
    as_of: datetime
    risks: list[WeatherRiskSummaryEntry]


class HourlyObservationRead(BaseModel):
    """One row of `weather_observations`. All numeric fields nullable
    because Open-Meteo can return NULL for individual variables on
    individual hours (e.g. solar radiation overnight)."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    provider_code: str
    air_temp_c: Decimal | None
    humidity_pct: Decimal | None
    precipitation_mm: Decimal | None
    wind_speed_m_s: Decimal | None
    wind_direction_deg: Decimal | None
    pressure_hpa: Decimal | None
    solar_radiation_w_m2: Decimal | None
    cloud_cover_pct: Decimal | None
    et0_mm: Decimal | None


class HourlyForecastRead(BaseModel):
    """One row of the latest-issuance forecast — `forecast_issued_at`
    is in the payload so consumers know how stale the snapshot is."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    forecast_issued_at: datetime
    provider_code: str
    air_temp_c: Decimal | None
    humidity_pct: Decimal | None
    precipitation_mm: Decimal | None
    precipitation_probability_pct: Decimal | None
    wind_speed_m_s: Decimal | None
    solar_radiation_w_m2: Decimal | None
    et0_mm: Decimal | None


class DailyForecastRead(BaseModel):
    """One day-bucket of the 5-day forecast.

    Aggregation rules (per Slice-4 alignment): high/low = max/min of
    hourly air_temp, precip_total = SUM, precip_probability = MAX of
    hourly probabilities, humidity = MEAN of hourly relative humidity
    (a mean, not a max — the daily average is what maps to the
    ``humidity`` weather index and to the disease models). ``date`` is
    in the farm's local timezone — not UTC — so "today" matches what
    the user sees on the farm.
    """

    date: date_type
    high_c: Decimal | None
    low_c: Decimal | None
    precip_mm_total: Decimal | None
    precip_probability_max_pct: Decimal | None
    humidity_mean_pct: Decimal | None


class ForecastResponse(BaseModel):
    """Response body of GET /blocks/{id}/weather/forecast."""

    farm_id: UUID
    provider_code: str
    timezone: str
    forecast_issued_at: datetime | None
    days: tuple[DailyForecastRead, ...]


class DerivedDailyRead(BaseModel):
    """One row of `weather_derived_daily`."""

    model_config = ConfigDict(from_attributes=True)

    date: date_type
    temp_min_c: Decimal | None
    temp_max_c: Decimal | None
    temp_mean_c: Decimal | None
    precip_mm_daily: Decimal | None
    precip_mm_7d: Decimal | None
    precip_mm_30d: Decimal | None
    et0_mm_daily: Decimal | None
    gdd_base10: Decimal | None
    gdd_base15: Decimal | None
    gdd_cumulative_base10_season: Decimal | None
    computed_at: datetime


class RefreshResponse(BaseModel):
    """POST /api/v1/blocks/{block_id}/weather/refresh response.

    Returns the farm IDs whose weather pipelines we actually fired —
    typically a single id (the block's farm), but the field is plural so
    the contract accommodates future per-block fetches without changing
    shape.
    """

    queued_farm_ids: tuple[UUID, ...]
    correlation_id: str | None = None
