"""Saved Agri Operation plans (Agri Operation PR 3).

``plan_allocations``: an operation manual allocated to a set of a farm's
blocks for one season, with the farm's own changes (decisions B1, B2, D1, D2,
C2, C4). Several can share a season (B2): each points at the season's
``vegetation_plans`` row. Applying one regenerates only its own
still-scheduled ``plan_activities``.

* ``blocks``            ``[{block_id, start_date}]``
* ``excluded_codes``    manual activity codes left out of this plan (D1)
* ``activity_edits``    ``{code: {product_name, dosage, notes, *_ar}}`` (D1)
* ``custom_activities`` activities added for this plan only (D2)
* ``date_overrides``    ``{block_id: {activity_key: "YYYY-MM-DD"}}``: dates
                        moved on the calendar or on the Plan board (C2, C4)

``plan_activities`` gains ``allocation_id``, ``activity_key`` (a manual
activity code, or ``custom:<id>``) and ``date_overridden``, and its ``source``
check widens to ``custom`` for activities a farm added to a saved plan.
Additive only; downgrade is safe only while no row uses ``custom``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0102"
down_revision: str | Sequence[str] | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_OLD = "source IN ('manual', 'template', 'recommendation')"
_SOURCE_NEW = "source IN ('manual', 'template', 'recommendation', 'custom')"
_JSONB_EMPTY_OBJECT = sa.text("'{}'::jsonb")
_JSONB_EMPTY_ARRAY = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "plan_allocations",
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
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vegetation_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Logical reference to public.plan_templates.id (cross-schema).
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("season_label", sa.Text(), nullable=False),
        sa.Column("season_year", sa.Integer(), nullable=False),
        sa.Column("start_mode", sa.Text(), nullable=False, server_default=sa.text("'same'")),
        sa.Column(
            "blocks",
            postgresql.JSONB(),
            nullable=False,
            server_default=_JSONB_EMPTY_ARRAY,
        ),
        sa.Column(
            "excluded_codes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "activity_edits",
            postgresql.JSONB(),
            nullable=False,
            server_default=_JSONB_EMPTY_OBJECT,
        ),
        sa.Column(
            "custom_activities",
            postgresql.JSONB(),
            nullable=False,
            server_default=_JSONB_EMPTY_ARRAY,
        ),
        sa.Column(
            "date_overrides",
            postgresql.JSONB(),
            nullable=False,
            server_default=_JSONB_EMPTY_OBJECT,
        ),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
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
        "ck_plan_allocations_start_mode",
        "plan_allocations",
        "start_mode IN ('same', 'per_block')",
    )
    op.create_index(
        "ix_plan_allocations_farm",
        "plan_allocations",
        ["farm_id", "season_year"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        """
        CREATE TRIGGER trg_plan_allocations_updated_at
        BEFORE UPDATE ON plan_allocations
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
        """
    )

    op.add_column(
        "plan_activities",
        sa.Column(
            "allocation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plan_allocations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("plan_activities", sa.Column("activity_key", sa.Text(), nullable=True))
    op.add_column(
        "plan_activities",
        sa.Column(
            "date_overridden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_constraint("ck_plan_activities_source", "plan_activities", type_="check")
    op.create_check_constraint("ck_plan_activities_source", "plan_activities", _SOURCE_NEW)
    op.create_index(
        "ix_plan_activities_allocation",
        "plan_activities",
        ["allocation_id", "block_id"],
        postgresql_where=sa.text("deleted_at IS NULL AND allocation_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_plan_activities_allocation", table_name="plan_activities")
    op.drop_constraint("ck_plan_activities_source", "plan_activities", type_="check")
    op.create_check_constraint("ck_plan_activities_source", "plan_activities", _SOURCE_OLD)
    op.drop_column("plan_activities", "date_overridden")
    op.drop_column("plan_activities", "activity_key")
    op.drop_column("plan_activities", "allocation_id")
    op.execute("DROP TRIGGER IF EXISTS trg_plan_allocations_updated_at ON plan_allocations")
    op.drop_index("ix_plan_allocations_farm", table_name="plan_allocations")
    op.drop_table("plan_allocations")
