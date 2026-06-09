"""Farm-block config model — PR-2: Subscriptions template tables.

Adds two new tables that hold the per-farm subscription template:

  * ``farm_imagery_template``  — PK ``(farm_id, product_id)``,
                                 mirrors ``imagery_aoi_subscriptions``
                                 knobs (cadence, cloud-cover, is_active).
  * ``farm_weather_template``  — PK ``(farm_id, provider_code)``,
                                 mirrors ``weather_subscriptions`` knobs.

These coexist with the existing ``farm_imagery_overrides`` /
``farm_weather_overrides`` (which keep feeding the three-tier
integration-settings resolver from PR #65). The two concepts are
different:

  * Override = "if cadence is null on a block, what value should the
    runtime resolver use for that knob?" → single row per farm,
    nullable knobs, consumed by the resolver.
  * Template = "what subscriptions should my blocks have?" → multi-row
    list of products/providers, consumed only by the Apply / Reset /
    Lock endpoints. Block reads do NOT consult the template.

Block-side subscription tables also pick up an ``applied_at``
``TIMESTAMPTZ`` so the UI can show "X of N blocks match the template"
status.

Revision ID: 0028
Revises: 0027
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- farm_imagery_template ----------------------------------------
    op.create_table(
        "farm_imagery_template",
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # Logical cross-schema FK to public.imagery_products.id; left as
        # a plain UUID column because Postgres FKs cannot cross schemas
        # cleanly and the catalog row is curated.
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("cadence_hours", sa.Integer(), nullable=False),
        sa.Column("cloud_cover_max_pct", sa.Integer(), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("farm_id", "product_id", name="pk_farm_imagery_template"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_farm_imagery_template_farm_id_farms",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cadence_hours > 0",
            name="ck_farm_imagery_template_cadence_positive",
        ),
        sa.CheckConstraint(
            "cloud_cover_max_pct IS NULL "
            "OR (cloud_cover_max_pct >= 0 AND cloud_cover_max_pct <= 100)",
            name="ck_farm_imagery_template_cloud_cover_range",
        ),
    )

    # ---- farm_weather_template ----------------------------------------
    op.create_table(
        "farm_weather_template",
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # Logical cross-schema FK to public.weather_providers.code (text).
        sa.Column("provider_code", sa.Text(), nullable=False),
        sa.Column("cadence_hours", sa.Integer(), nullable=False),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("farm_id", "provider_code", name="pk_farm_weather_template"),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_farm_weather_template_farm_id_farms",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cadence_hours > 0",
            name="ck_farm_weather_template_cadence_positive",
        ),
    )

    # ---- applied_at on block-side subscription tables -----------------
    # When Apply reconciles a block to the template, this is stamped to
    # now(). The UI uses (applied_at == updated_at-of-template) plus a
    # row-by-row content check to drive the "X of N match" status.
    op.add_column(
        "imagery_aoi_subscriptions",
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "weather_subscriptions",
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weather_subscriptions", "applied_at")
    op.drop_column("imagery_aoi_subscriptions", "applied_at")
    op.drop_table("farm_weather_template")
    op.drop_table("farm_imagery_template")
