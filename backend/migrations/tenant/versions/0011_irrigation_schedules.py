"""irrigation_schedules — model-driven daily watering recommendations.

PR-7 of FarmDM rollout. Consumes:

  * Weather ET₀ from `weather_derived_daily.et0_mm_daily` (PR-C).
  * Recent precipitation from `weather_derived_daily.precip_mm_*`.
  * Crop coefficient (Kc) resolved from the block's current crop +
    its growth stage via `crops.phenology_stages` /
    `crop_varieties.phenology_stages_override` (PR-2 / PR-3).

Each row is a *recommendation* the operator can accept (apply) or
override (skip) — irrigation isn't fully automated. The state machine
is `pending → applied | skipped`. Applied rows carry the actual volume
the operator delivered, which may differ from `recommended_mm` (e.g.
they had to round up or down based on system capacity).

Idempotency: partial UNIQUE on `(block_id, scheduled_for) WHERE
status = 'pending'` — re-running the daily Beat sweep keeps the same
pending recommendation rather than spawning duplicates.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "irrigation_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        # The recommendation itself.
        sa.Column("recommended_mm", sa.Numeric(7, 2), nullable=False),
        # Inputs that produced it — captured at compute time so the
        # rationale survives even if upstream tables change later.
        sa.Column("kc_used", sa.Numeric(5, 3), nullable=True),
        sa.Column("et0_mm_used", sa.Numeric(7, 2), nullable=True),
        sa.Column("recent_precip_mm", sa.Numeric(7, 2), nullable=True),
        sa.Column("growth_stage_context", sa.Text(), nullable=True),
        sa.Column("soil_moisture_pct", sa.Numeric(5, 2), nullable=True),
        # State machine.
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("applied_volume_mm", sa.Numeric(7, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        # Audit.
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_irrigation_schedules_status",
        "irrigation_schedules",
        "status IN ('pending', 'applied', 'skipped')",
    )
    op.create_check_constraint(
        "ck_irrigation_schedules_recommended_nonneg",
        "irrigation_schedules",
        "recommended_mm >= 0",
    )
    op.create_index(
        "uq_irrigation_schedules_block_date_pending",
        "irrigation_schedules",
        ["block_id", "scheduled_for"],
        unique=True,
        postgresql_where=sa.text("status = 'pending' AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_irrigation_schedules_block_date",
        "irrigation_schedules",
        ["block_id", sa.text("scheduled_for DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_irrigation_schedules_pending_date",
        "irrigation_schedules",
        ["scheduled_for"],
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status = 'pending'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_irrigation_schedules_pending_date", table_name="irrigation_schedules"
    )
    op.drop_index(
        "ix_irrigation_schedules_block_date", table_name="irrigation_schedules"
    )
    op.drop_index(
        "uq_irrigation_schedules_block_date_pending", table_name="irrigation_schedules"
    )
    op.drop_constraint(
        "ck_irrigation_schedules_recommended_nonneg",
        "irrigation_schedules",
        type_="check",
    )
    op.drop_constraint(
        "ck_irrigation_schedules_status", "irrigation_schedules", type_="check"
    )
    op.drop_table("irrigation_schedules")
