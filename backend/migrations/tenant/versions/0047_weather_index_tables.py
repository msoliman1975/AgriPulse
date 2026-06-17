"""Weather-index projection + climatology baselines (Weather-Indices PR-W2).

Two per-tenant **regular** tables that turn the existing weather data
into first-class index timeseries (catalog seeded in public 0037):

  1. `weather_index_daily` — one row per (farm_id, date, index_code).
     A materialised projection of `weather_observations` +
     `weather_derived_daily` into the 7 catalog indices, plus a
     `baseline_deviation` z-score (NULL until the PR-W3 climatology
     sweep populates `weather_index_baselines`). Regular table, not a
     hypertable: daily granularity, and the climatology join is trivial.

  2. `weather_index_baselines` — per (farm_id, index_code, day_of_year)
     rolling mean ± std (farm-scoped port of `block_index_baselines`).
     Populated weekly in PR-W3; the projection reads it to compute the
     z-score at write time.

Both carry a CASCADE FK to `farms` (matches `weather_derived_daily`).
Weather is farm-centroid data, so these are farm-keyed, not block-keyed.

Revision ID: 0047
Revises: 0046
Create Date: 2026-06-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | Sequence[str] | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- weather_index_daily (regular table) --------------------------
    op.create_table(
        "weather_index_daily",
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("index_code", sa.Text(), nullable=False),
        # Headline daily value + optional spread; nullable because a
        # partial / gap day can leave any index undefined.
        sa.Column("value", sa.Numeric(10, 3), nullable=True),
        sa.Column("value_min", sa.Numeric(10, 3), nullable=True),
        sa.Column("value_max", sa.Numeric(10, 3), nullable=True),
        # Extra per-index facets (e.g. wind mean direction, daily
        # insolation, 7-/30-day rainfall totals). Decimals serialised as
        # strings per the Decimal→string JSON convention.
        sa.Column(
            "value_aux",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Z-score vs the matching (farm, index, day_of_year) baseline.
        # NULL until PR-W3 seeds climatology.
        sa.Column("baseline_deviation", sa.Numeric(8, 4), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("farm_id", "date", "index_code", name="pk_weather_index_daily"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_weather_index_daily_farm_id_farms",
            ondelete="CASCADE",
        ),
    )
    # Timeseries read filters (farm_id, index_code, date-range).
    op.create_index(
        "ix_weather_index_daily_farm_code_date",
        "weather_index_daily",
        ["farm_id", "index_code", "date"],
    )

    # ---- weather_index_baselines (regular table) ----------------------
    op.create_table(
        "weather_index_baselines",
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_code", sa.Text(), nullable=False),
        sa.Column("day_of_year", sa.SmallInteger(), nullable=False),
        sa.Column("baseline_mean", sa.Numeric(10, 4), nullable=False),
        sa.Column("baseline_std", sa.Numeric(10, 4), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("window_days", sa.SmallInteger(), nullable=False, server_default=sa.text("7")),
        sa.Column("years_observed", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "farm_id", "index_code", "day_of_year", name="pk_weather_index_baselines"
        ),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_weather_index_baselines_farm_id_farms",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("weather_index_baselines")
    op.drop_index("ix_weather_index_daily_farm_code_date", table_name="weather_index_daily")
    op.drop_table("weather_index_daily")
