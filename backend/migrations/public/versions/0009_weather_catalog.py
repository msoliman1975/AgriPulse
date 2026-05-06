"""Weather provider catalog + derived-signals catalog.

Per data_model § 8 and the Slice 4 PR-A plan. Two `public` tables curated
by platform admins:

  1. `weather_providers` — registry of weather data sources. MVP knows
     `open_meteo` only; future sources (e.g., NOAA GFS) drop in here.
     Mirrors `imagery_providers` shape so admin tooling stays uniform.

  2. `weather_derived_signals_catalog` — definitions of the derived
     daily signals the nightly job computes (GDD bases, ET₀ daily,
     cumulative rainfall windows). Mirrors `indices_catalog`. The
     formulas live in `weather/derivations.py` (PR-C); this catalog is
     the i18n + units + display surface.

Per the locked Slice-4 decisions, weather is sampled at the *farm*
centroid (data_model § 8). Hypertables and the derived-daily table
land in the tenant migration alongside the per-block subscription
table — see migrations/tenant/versions/0005_weather_tables.py.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- public.weather_providers --------------------------------------
    op.create_table(
        "weather_providers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "config_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
        sa.UniqueConstraint("code", name="uq_weather_providers_code"),
        sa.CheckConstraint(
            "kind IN ('open_api','commercial_api')",
            name="ck_weather_providers_kind",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_weather_providers_updated_at "
        "BEFORE UPDATE ON public.weather_providers "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.weather_derived_signals_catalog ------------------------
    # The nightly derivation job (PR-C) reads this catalog to know which
    # signals to compute and to surface display metadata to the frontend.
    # `code` matches the column name in `weather_derived_daily`.
    op.create_table(
        "weather_derived_signals_catalog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
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
        sa.UniqueConstraint("code", name="uq_weather_derived_signals_catalog_code"),
    )
    op.execute(
        "CREATE TRIGGER trg_weather_derived_signals_catalog_updated_at "
        "BEFORE UPDATE ON public.weather_derived_signals_catalog "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_weather_derived_signals_catalog_updated_at "
        "ON public.weather_derived_signals_catalog"
    )
    op.drop_table("weather_derived_signals_catalog")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_weather_providers_updated_at ON public.weather_providers"
    )
    op.drop_table("weather_providers")
