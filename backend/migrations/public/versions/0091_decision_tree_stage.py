"""A tree says which engine it belongs to, and the sweep reads only 'live'.

Part 4 of the unified decision tree engine, second half.

`decision_tree_versions.definition` (migration 0090) says what shape one
*version* holds. This says what the *tree* is for, and it is a separate
question: a beta tree can be published — its author needs a published
version to dry-run against and to hand to a reviewer — without the nightly
sweep ever walking it.

    stage = 'live'   the eleven index trees and everything beside them.
                     The sweep runs these. Every existing row.
    stage = 'beta'   authored against the folding engine. Published, dry-run
                     and read by the designer. The sweep never sees it.

The default is `'live'`, so every row that exists keeps behaving exactly as
it does today and no backfill is needed. `list_active_trees_with_current_version`
— the one query the sweep resolves its tree set from — gains
`AND t.stage = 'live'`, which is the whole enforcement. Wiring the sweep to
the folding engine is a later piece of work; until it lands, a published
beta tree produces nothing anywhere, which is the intended state.

The value is CHECK constrained rather than left free text because it is
read as a filter in a hot query. A typo that lets a beta tree into the
sweep writes recommendations at growers, and there is no error anywhere on
the way.

Design: docs/proposals/unified-decision-tree-engine.md section 9.

Revision ID: 0091
Revises: 0090
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0091"
down_revision: str | Sequence[str] | None = "0090"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGE_CHECK = "ck_decision_trees_stage"


def upgrade() -> None:
    op.add_column(
        "decision_trees",
        sa.Column("stage", sa.Text(), nullable=False, server_default=sa.text("'live'")),
        schema="public",
    )
    op.create_check_constraint(
        _STAGE_CHECK,
        "decision_trees",
        "stage IN ('live', 'beta')",
        schema="public",
    )
    # The sweep's tree query filters on this and on nothing else that is
    # cheap to combine with it, so the index is on the one column.
    op.create_index(
        "ix_decision_trees_stage",
        "decision_trees",
        ["stage"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_decision_trees_stage", table_name="decision_trees", schema="public")
    op.execute(f"ALTER TABLE public.decision_trees DROP CONSTRAINT IF EXISTS {_STAGE_CHECK}")
    op.drop_column("decision_trees", "stage", schema="public")
