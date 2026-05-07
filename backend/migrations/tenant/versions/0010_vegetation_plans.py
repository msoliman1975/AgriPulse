"""vegetation_plans + plan_activities — forward-looking seasonal planning.

PR-6 of FarmDM rollout. Distinct from `block_crops` (which tracks
*current and historical* crop assignments per block); plans are the
*future-looking* schedule of activities the team intends to do.

Two tables:

  * `vegetation_plans` — one per farm per season. Carries the plan's
    state (draft → active → completed → archived) and metadata.
    Partial UNIQUE on `(farm_id, season_label) WHERE deleted_at IS NULL`
    keeps each farm's per-season plan canonical.
  * `plan_activities` — the schedule items: planting, fertilizing,
    spraying, etc. Each targets one block (FK ON DELETE RESTRICT —
    deleting a block with scheduled activities should fail loud, not
    silently orphan the schedule). Activity states are
    `scheduled → in_progress → completed | skipped`.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- vegetation_plans ----------------------------------------------
    op.create_table(
        "vegetation_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season_label", sa.Text(), nullable=False),
        sa.Column("season_year", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_vegetation_plans_status",
        "vegetation_plans",
        "status IN ('draft', 'active', 'completed', 'archived')",
    )
    op.create_index(
        "uq_vegetation_plans_farm_season_active",
        "vegetation_plans",
        ["farm_id", "season_label"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_vegetation_plans_farm_year",
        "vegetation_plans",
        ["farm_id", "season_year"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- plan_activities -----------------------------------------------
    op.create_table(
        "plan_activities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vegetation_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("dosage", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'scheduled'"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", postgresql.UUID(as_uuid=True), nullable=True),
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
        "ck_plan_activities_activity_type",
        "plan_activities",
        "activity_type IN ('planting','fertilizing','spraying','pruning',"
        "'harvesting','irrigation','soil_prep','observation')",
    )
    op.create_check_constraint(
        "ck_plan_activities_status",
        "plan_activities",
        "status IN ('scheduled','in_progress','completed','skipped')",
    )
    op.create_index(
        "ix_plan_activities_plan_date",
        "plan_activities",
        ["plan_id", "scheduled_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_plan_activities_block_date",
        "plan_activities",
        ["block_id", "scheduled_date"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_plan_activities_status_date",
        "plan_activities",
        ["status", "scheduled_date"],
        postgresql_where=sa.text("deleted_at IS NULL AND status IN ('scheduled','in_progress')"),
    )


def downgrade() -> None:
    op.drop_index("ix_plan_activities_status_date", table_name="plan_activities")
    op.drop_index("ix_plan_activities_block_date", table_name="plan_activities")
    op.drop_index("ix_plan_activities_plan_date", table_name="plan_activities")
    op.drop_constraint("ck_plan_activities_status", "plan_activities", type_="check")
    op.drop_constraint("ck_plan_activities_activity_type", "plan_activities", type_="check")
    op.drop_table("plan_activities")

    op.drop_index("ix_vegetation_plans_farm_year", table_name="vegetation_plans")
    op.drop_index("uq_vegetation_plans_farm_season_active", table_name="vegetation_plans")
    op.drop_constraint("ck_vegetation_plans_status", "vegetation_plans", type_="check")
    op.drop_table("vegetation_plans")
