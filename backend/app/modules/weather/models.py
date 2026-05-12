"""Weather ORM models. Catalogs in `public`; subscriptions, hypertables,
and derived-daily in the per-tenant schema (search_path resolves).
data_model § 8.

Subscription rows are per-block (matches the imagery UX) but the
hypertables and derived-daily are keyed on **farm_id** because Open-
Meteo's grid is ~9km — fetching per block would just duplicate the
parent farm's data. PR-B's ingestion task groups active subscriptions
by farm_id and fetches once per (farm_id, cycle).
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class WeatherProvider(Base, TimestampedMixin):
    """`public.weather_providers` — curated provider catalog."""

    __tablename__ = "weather_providers"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    config_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class WeatherDerivedSignalCatalog(Base, TimestampedMixin):
    """`public.weather_derived_signals_catalog` — i18n + units for derived signals."""

    __tablename__ = "weather_derived_signals_catalog"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class WeatherSubscription(Base, TimestampedMixin):
    """`tenant_<id>.weather_subscriptions` — per-block weather subscription.

    Logical cross-schema FK: `provider_code` references
    `public.weather_providers.code` (text). data_model § 8 keys hypertable
    rows on `provider_code` rather than a UUID.
    """

    __tablename__ = "weather_subscriptions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_code: Mapped[str] = mapped_column(Text, nullable=False)
    cadence_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    last_successful_ingest_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WeatherIngestionAttempt(Base):
    """`tenant_<id>.weather_ingestion_attempts` — per-attempt history.

    One row per (subscription, fetch attempt). Both success and failure
    paths write here; `status` discriminates. `duration_ms` is a
    generated column computed from completed_at - started_at.

    Migration 0021.
    """

    __tablename__ = "weather_ingestion_attempts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "weather_subscriptions.id",
            name="fk_weather_ingestion_attempts_subscription_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    block_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    farm_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    provider_code: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    rows_ingested: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Generated column on the DB side; expose as read-only here.
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WeatherObservation(Base):
    """`tenant_<id>.weather_observations` — TimescaleDB hypertable.

    No PK column: a hypertable's unique constraint must include the
    time partitioning column. The composite UNIQUE on
    (time, farm_id, provider_code) is the per-(hour, farm, provider)
    idempotency key.
    """

    __tablename__ = "weather_observations"
    __table_args__: tuple[UniqueConstraint | dict[str, object], ...] = (
        UniqueConstraint(
            "time",
            "farm_id",
            "provider_code",
            name="uq_weather_observations_time_farm_provider",
        ),
        {},
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    farm_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    provider_code: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)

    air_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    precipitation_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    wind_speed_m_s: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    wind_direction_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    pressure_hpa: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    solar_radiation_w_m2: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    cloud_cover_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    et0_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WeatherForecast(Base):
    """`tenant_<id>.weather_forecasts` — TimescaleDB hypertable.

    Keep-all-issuances: the UNIQUE on
    (time, farm_id, provider_code, forecast_issued_at) is the
    idempotency key — re-fetching the same issuance is a no-op, but
    successive issuances coexist so forecast-vs-actual analysis (P2)
    has the raw history.
    """

    __tablename__ = "weather_forecasts"
    __table_args__: tuple[UniqueConstraint | dict[str, object], ...] = (
        UniqueConstraint(
            "time",
            "farm_id",
            "provider_code",
            "forecast_issued_at",
            name="uq_weather_forecasts_time_farm_provider_issued",
        ),
        {},
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    forecast_issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    farm_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    provider_code: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)

    air_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    humidity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    precipitation_mm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    precipitation_probability_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    wind_speed_m_s: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    solar_radiation_w_m2: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    et0_mm: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WeatherDerivedDaily(Base):
    """`tenant_<id>.weather_derived_daily` — per-(farm, day) derived signals.

    Regular table (not a continuous aggregate) because GDD requires
    per-block crop-base-temp logic resolved in application code —
    data_model § 8.4.
    """

    __tablename__ = "weather_derived_daily"
    __table_args__: tuple[PrimaryKeyConstraint | dict[str, object], ...] = (
        PrimaryKeyConstraint("farm_id", "date", name="pk_weather_derived_daily"),
        {},
    )

    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)

    gdd_base10: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    gdd_base15: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    gdd_cumulative_base10_season: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    et0_mm_daily: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    precip_mm_daily: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    precip_mm_7d: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    precip_mm_30d: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    temp_min_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    temp_max_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    temp_mean_c: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
