"""Per-tenant weather: subscriptions, observations, forecasts, derived daily.

Per data_model § 8 and the locked Slice-4 decisions:

  - `weather_subscriptions` is keyed on **block_id** (mirrors imagery's
    per-block UX). Hypertables and the derived-daily table key on
    **farm_id** because Open-Meteo's grid is ~9km — fetching per block
    would just duplicate the parent farm's data. PR-B's ingestion task
    deduplicates active subscriptions to one fetch per (farm_id, cycle).

  - `weather_forecasts` keeps every forecast issuance — the UNIQUE on
    (time, farm_id, provider_code, forecast_issued_at) is the
    idempotency key, not a "latest only" key. Forecast-vs-actual
    accuracy analysis (P2) needs the raw history.

  - `weather_observations` and `weather_forecasts` are TimescaleDB
    hypertables; `weather_derived_daily` is a regular table because
    GDD requires application-side per-block crop-base-temp logic
    (data_model § 8.4).

  - No FK constraints on the hypertable rows (matches the imagery
    pattern in 0003); the regular `weather_derived_daily` carries one
    to `farms`. Tenant-internal FKs only — provider_code is text and
    references public.weather_providers.code as a logical FK.

Retention policies are deferred to PR-B alongside ingestion code, so the
operator-facing knobs land together.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- weather_subscriptions ----------------------------------------
    # Per-block per the hybrid decision. ON DELETE CASCADE: archiving a
    # block also disables its weather subscription. `provider_code` is
    # a logical cross-schema FK to public.weather_providers.code (text,
    # matching data_model § 8.2's column type for the hypertables).
    op.create_table(
        "weather_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_code", sa.Text(), nullable=False),
        # NULL means "use tenant default" — the resolved cadence drops
        # into the ingestion job's `cadence_hours` snapshot at run time.
        sa.Column("cadence_hours", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column("last_successful_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name="fk_weather_subscriptions_block_id_blocks",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cadence_hours IS NULL OR cadence_hours > 0",
            name="ck_weather_subscriptions_cadence_positive",
        ),
    )
    op.create_index(
        "uq_weather_subscriptions_block_provider_active",
        "weather_subscriptions",
        ["block_id", "provider_code"],
        unique=True,
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.create_index(
        "ix_weather_subscriptions_last_attempted",
        "weather_subscriptions",
        ["last_attempted_at"],
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.execute(
        "CREATE TRIGGER trg_weather_subscriptions_updated_at "
        "BEFORE UPDATE ON weather_subscriptions "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- weather_observations (hypertable) ----------------------------
    # Columns per data_model § 8.2. No PK: a hypertable's unique
    # constraint must include the time partition column. UNIQUE on
    # (time, farm_id, provider_code) is the per-(hour, farm, provider)
    # idempotency key.
    op.create_table(
        "weather_observations",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_code", sa.Text(), nullable=False),
        sa.Column("air_temp_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("humidity_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("precipitation_mm", sa.Numeric(6, 2), nullable=True),
        sa.Column("wind_speed_m_s", sa.Numeric(5, 2), nullable=True),
        sa.Column("wind_direction_deg", sa.Numeric(5, 1), nullable=True),
        sa.Column("pressure_hpa", sa.Numeric(6, 2), nullable=True),
        sa.Column("solar_radiation_w_m2", sa.Numeric(7, 2), nullable=True),
        sa.Column("cloud_cover_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("et0_mm", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "time",
            "farm_id",
            "provider_code",
            name="uq_weather_observations_time_farm_provider",
        ),
        sa.CheckConstraint(
            "humidity_pct IS NULL OR (humidity_pct BETWEEN 0 AND 100)",
            name="ck_weather_observations_humidity_range",
        ),
        sa.CheckConstraint(
            "cloud_cover_pct IS NULL OR (cloud_cover_pct BETWEEN 0 AND 100)",
            name="ck_weather_observations_cloud_cover_range",
        ),
    )
    op.execute(
        """
        SELECT create_hypertable(
            'weather_observations',
            'time',
            partitioning_column => 'farm_id',
            number_partitions => 4,
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        )
        """
    )
    op.execute(
        """
        ALTER TABLE weather_observations SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'farm_id'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy("
        "'weather_observations', INTERVAL '30 days', if_not_exists => TRUE)"
    )
    op.create_index(
        "ix_weather_observations_farm_time",
        "weather_observations",
        ["farm_id", sa.text("time DESC")],
    )

    # ---- weather_forecasts (hypertable, keep-all issuances) ----------
    # Columns per data_model § 8.3. Idempotency key includes
    # `forecast_issued_at` so every fetch's snapshot is preserved
    # (locked decision: keep all issuances). Latest-forecast queries
    # use DISTINCT ON (time) ORDER BY time, forecast_issued_at DESC.
    op.create_table(
        "weather_forecasts",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_code", sa.Text(), nullable=False),
        sa.Column("air_temp_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("humidity_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("precipitation_mm", sa.Numeric(6, 2), nullable=True),
        sa.Column("precipitation_probability_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("wind_speed_m_s", sa.Numeric(5, 2), nullable=True),
        sa.Column("solar_radiation_w_m2", sa.Numeric(7, 2), nullable=True),
        sa.Column("et0_mm", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "time",
            "farm_id",
            "provider_code",
            "forecast_issued_at",
            name="uq_weather_forecasts_time_farm_provider_issued",
        ),
        sa.CheckConstraint(
            "humidity_pct IS NULL OR (humidity_pct BETWEEN 0 AND 100)",
            name="ck_weather_forecasts_humidity_range",
        ),
        sa.CheckConstraint(
            "precipitation_probability_pct IS NULL OR "
            "(precipitation_probability_pct BETWEEN 0 AND 100)",
            name="ck_weather_forecasts_precip_prob_range",
        ),
    )
    op.execute(
        """
        SELECT create_hypertable(
            'weather_forecasts',
            'time',
            partitioning_column => 'farm_id',
            number_partitions => 4,
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        )
        """
    )
    op.execute(
        """
        ALTER TABLE weather_forecasts SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'farm_id'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy("
        "'weather_forecasts', INTERVAL '14 days', if_not_exists => TRUE)"
    )
    # Per data_model § 8.3: "what was the latest forecast for tomorrow?"
    op.create_index(
        "ix_weather_forecasts_farm_time_issued",
        "weather_forecasts",
        ["farm_id", sa.text("time DESC"), sa.text("forecast_issued_at DESC")],
    )
    op.create_index(
        "ix_weather_forecasts_issued_at",
        "weather_forecasts",
        ["forecast_issued_at"],
    )

    # ---- weather_derived_daily (regular table) ------------------------
    # PK (farm_id, date). data_model § 8.4 notes this could be a CAgg
    # but stays a regular table because GDD needs per-block crop-base-
    # temp logic resolved in application code.
    op.create_table(
        "weather_derived_daily",
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("gdd_base10", sa.Numeric(8, 2), nullable=True),
        sa.Column("gdd_base15", sa.Numeric(8, 2), nullable=True),
        sa.Column("gdd_cumulative_base10_season", sa.Numeric(10, 2), nullable=True),
        sa.Column("et0_mm_daily", sa.Numeric(5, 2), nullable=True),
        sa.Column("precip_mm_daily", sa.Numeric(6, 2), nullable=True),
        sa.Column("precip_mm_7d", sa.Numeric(7, 2), nullable=True),
        sa.Column("precip_mm_30d", sa.Numeric(8, 2), nullable=True),
        sa.Column("temp_min_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("temp_max_c", sa.Numeric(5, 2), nullable=True),
        sa.Column("temp_mean_c", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("farm_id", "date", name="pk_weather_derived_daily"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_weather_derived_daily_farm_id_farms",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_weather_derived_daily_date",
        "weather_derived_daily",
        ["date"],
    )


def downgrade() -> None:
    # weather_derived_daily (regular table) ----------------------------
    op.drop_index("ix_weather_derived_daily_date", table_name="weather_derived_daily")
    op.drop_table("weather_derived_daily")

    # weather_forecasts (hypertable) -----------------------------------
    op.execute("SELECT remove_compression_policy('weather_forecasts', if_exists => TRUE)")
    op.drop_index("ix_weather_forecasts_issued_at", table_name="weather_forecasts")
    op.drop_index("ix_weather_forecasts_farm_time_issued", table_name="weather_forecasts")
    op.drop_table("weather_forecasts")

    # weather_observations (hypertable) --------------------------------
    op.execute("SELECT remove_compression_policy('weather_observations', if_exists => TRUE)")
    op.drop_index("ix_weather_observations_farm_time", table_name="weather_observations")
    op.drop_table("weather_observations")

    # weather_subscriptions --------------------------------------------
    op.execute(
        "DROP TRIGGER IF EXISTS trg_weather_subscriptions_updated_at " "ON weather_subscriptions"
    )
    op.drop_index(
        "ix_weather_subscriptions_last_attempted",
        table_name="weather_subscriptions",
    )
    op.drop_index(
        "uq_weather_subscriptions_block_provider_active",
        table_name="weather_subscriptions",
    )
    op.drop_table("weather_subscriptions")
