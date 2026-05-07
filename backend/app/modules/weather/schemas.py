"""Pydantic schemas for the weather module's REST surface.

snake_case JSON, RFC 3339 timestamps, units called out in the column
(°C, mm, m/s, etc.) per ARCHITECTURE.md § 8.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
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
    hourly probabilities. ``date`` is in the farm's local timezone —
    not UTC — so "today" matches what the user sees on the farm.
    """

    date: date_type
    high_c: Decimal | None
    low_c: Decimal | None
    precip_mm_total: Decimal | None
    precip_probability_max_pct: Decimal | None


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
