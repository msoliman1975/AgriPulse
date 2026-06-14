"""Link plan_activities / vegetation_plans to applied plan templates.

Lets the apply engine (PR-E2) mark generated rows so re-apply is
idempotent (regenerate template rows, preserve manual/completed) and the
board can badge "from template" + "scheduled at <stage>".

All adds nullable/defaulted -> data-safe; downgrade drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plan_activities",
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
    )
    op.add_column(
        "plan_activities",
        sa.Column("applied_template_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "plan_activities",
        sa.Column("template_activity_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "plan_activities",
        sa.Column("anchored_stage_code", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_plan_activities_source",
        "plan_activities",
        "source IN ('manual', 'template', 'recommendation')",
    )
    # Speeds the idempotent regen: DELETE … WHERE plan_id, block_id,
    # applied_template_id for template-generated rows.
    op.create_index(
        "ix_plan_activities_applied_template",
        "plan_activities",
        ["plan_id", "block_id", "applied_template_id"],
        postgresql_where=sa.text("applied_template_id IS NOT NULL"),
    )
    op.add_column(
        "vegetation_plans",
        sa.Column("applied_template_id", PG_UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vegetation_plans", "applied_template_id")
    op.drop_index("ix_plan_activities_applied_template", table_name="plan_activities")
    op.drop_constraint("ck_plan_activities_source", "plan_activities", type_="check")
    op.drop_column("plan_activities", "anchored_stage_code")
    op.drop_column("plan_activities", "template_activity_id")
    op.drop_column("plan_activities", "applied_template_id")
    op.drop_column("plan_activities", "source")
