"""Plan-template catalog (public): templates + milestones + activities.

Platform-curated agriculture plan templates targeted by crop-taxonomy
``crop_path``. Activities anchor to start / a milestone / a phenology
``stage`` (the spine). Tenants apply a template to materialise the
existing vegetation_plans / plan_activities (tenant migration 0041 adds
the link columns).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID7 = sa.text("uuid_generate_v7()")


def upgrade() -> None:
    op.create_table(
        "plan_templates",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID7),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("crop_path", sa.Text(), nullable=False),
        sa.Column("crop_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
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
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_plan_templates_status",
        ),
        schema="public",
    )
    op.create_index(
        "uq_plan_templates_code",
        "plan_templates",
        ["code"],
        unique=True,
        schema="public",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_plan_templates_crop_path", "plan_templates", ["crop_path"], schema="public")

    op.create_table(
        "plan_template_milestones",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID7),
        sa.Column("template_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("day_from_start", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["public.plan_templates.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("template_id", "code", name="uq_plan_template_milestone_code"),
        sa.CheckConstraint("day_from_start >= 0", name="ck_plan_template_milestone_day"),
        schema="public",
    )
    op.create_index(
        "ix_plan_template_milestones_template",
        "plan_template_milestones",
        ["template_id"],
        schema="public",
    )

    op.create_table(
        "plan_template_activities",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, server_default=_UUID7),
        sa.Column("template_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("anchor", sa.Text(), nullable=False, server_default=sa.text("'start'")),
        sa.Column("milestone_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("stage_code", sa.Text(), nullable=True),
        sa.Column("offset_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_days", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("dosage", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
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
        sa.Column("created_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["template_id"], ["public.plan_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["milestone_id"], ["public.plan_template_milestones.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "anchor IN ('start', 'milestone', 'stage')",
            name="ck_plan_template_activity_anchor",
        ),
        sa.CheckConstraint(
            "(anchor <> 'milestone') OR (milestone_id IS NOT NULL)",
            name="ck_plan_template_activity_milestone_ref",
        ),
        sa.CheckConstraint(
            "(anchor <> 'stage') OR (stage_code IS NOT NULL)",
            name="ck_plan_template_activity_stage_ref",
        ),
        sa.CheckConstraint("duration_days >= 1", name="ck_plan_template_activity_duration"),
        schema="public",
    )
    op.create_index(
        "ix_plan_template_activities_template",
        "plan_template_activities",
        ["template_id"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("plan_template_activities", schema="public")
    op.drop_table("plan_template_milestones", schema="public")
    op.drop_table("plan_templates", schema="public")
