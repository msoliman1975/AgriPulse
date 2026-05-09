"""farm_weather_overrides + farm_imagery_overrides — Farm-tier resolver inputs.

Per `docs/proposals/admin-portals-and-settings.md` §3.4 + §3.5.

Both tables are thin: one row per Farm with the columns that can be
overridden. NULL on a column means "fall through to the next tier
(tenant override → platform default)".

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "farm_weather_overrides",
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("provider_code", sa.Text(), nullable=True),
        sa.Column("cadence_hours", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_farm_weather_overrides_farm_id_farms",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cadence_hours IS NULL OR cadence_hours > 0",
            name="ck_farm_weather_overrides_cadence_positive",
        ),
    )

    op.create_table(
        "farm_imagery_overrides",
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("product_code", sa.Text(), nullable=True),
        sa.Column("cloud_cover_threshold_pct", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["farm_id"],
            ["farms.id"],
            name="fk_farm_imagery_overrides_farm_id_farms",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cloud_cover_threshold_pct IS NULL "
            "OR (cloud_cover_threshold_pct >= 0 AND cloud_cover_threshold_pct <= 100)",
            name="ck_farm_imagery_overrides_cloud_cover_range",
        ),
    )


def downgrade() -> None:
    op.drop_table("farm_imagery_overrides")
    op.drop_table("farm_weather_overrides")
