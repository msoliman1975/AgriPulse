"""Let a farm turn a decision tree off for itself.

Until now every active tree visible to a tenant ran against every active
block of every farm. The only filters were the tree's own targeting axes
(crop, country, soil texture), which the farm cannot change. A farm that
does not want a tree had no way to say so.

This table records the exception, not the rule. A row means "this farm
has turned this tree off". A farm with no rows keeps today's behaviour,
so the default stays "all trees run".

The exclusion list is deliberately an opt-out and not an allow-list. With
an allow-list, a tree published after a farm saved its choices would
reach nobody, and nothing would report that. With an opt-out, a new tree
reaches every farm the way it does today.

`tree_id` is a logical reference to `public.decision_trees.id` with no
foreign key. A real FK from a tenant schema into `public` makes
`DROP SCHEMA tenant_x` take an ACCESS EXCLUSIVE lock platform-wide, which
is why no tenant table has one.

A tree turned off stops being evaluated from the next sweep onward. It
does not close the recommendations or alerts it already opened; those
stay in the Action Center until somebody acts on them. Turning the tree
back on deletes the row and the tree resumes at the next sweep.

The second half of this migration widens the `skip_axis` CHECK on
`decision_tree_eval_traces` from ('crop','country','soil') to include
'farm'. A turned-off tree is recorded as a skipped trace naming that
axis, the same as a tree the block's crop does not match. Without the
new value the trace insert fails and the whole block's evaluation fails
with it. Recording the skip is the point: a tree that stops producing
cards with no trace and no log is not something anyone can explain
later.

Revision ID: 0089
Revises: 0088
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "farm_tree_exclusions",
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Logical reference to public.decision_trees.id. No FK on purpose.
        sa.Column("tree_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "disabled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Logical reference to public.users.id; nullable so a system-made
        # exclusion (none today) does not need a user.
        sa.Column("disabled_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # The sweep loads every exclusion for a tenant in one query and groups by
    # farm; the primary key already leads with farm_id, so no second index.

    _replace_skip_axis_check(("crop", "country", "soil", "farm"))


def downgrade() -> None:
    _replace_skip_axis_check(("crop", "country", "soil"))
    op.drop_table("farm_tree_exclusions")


def _replace_skip_axis_check(axes: tuple[str, ...]) -> None:
    """Rewrite the `skip_axis` CHECK on `decision_tree_eval_traces`.

    The constraint is found by reading `pg_constraint` rather than by name.
    Migration 0062 declared it as ``name="skip_axis"`` and the metadata
    naming convention expands that, so the live name is not the literal in
    the migration source and has been doubled on other tables in this
    schema. Matching on the column the check mentions is the reliable way.
    """
    bind = op.get_bind()
    rows = bind.execute(
        text(
            """
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = current_schema()
              AND t.relname = 'decision_tree_eval_traces'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%skip_axis%'
            """
        )
    ).all()
    for row in rows:
        bind.execute(
            text(f'ALTER TABLE decision_tree_eval_traces DROP CONSTRAINT "{row.conname}"')
        )
    allowed = ", ".join(f"'{axis}'" for axis in axes)
    bind.execute(
        text(
            "ALTER TABLE decision_tree_eval_traces "
            "ADD CONSTRAINT ck_decision_tree_eval_traces_skip_axis "
            f"CHECK (skip_axis IS NULL OR skip_axis IN ({allowed}))"
        )
    )
