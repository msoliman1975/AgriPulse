"""Decision-tree execution scope (per-cell scope, PR-C1).

Adds ``decision_trees.scope`` — the granularity a tree executes at:

  * ``block`` (default) — one evaluation per block, as today.
  * ``cell``            — one evaluation per sub-block grid cell, so a tree
                          can act on the water-stressed corner of a block.

Only ``cell``-scoped trees fan out over grid cells; every existing tree
defaults to ``block`` and is completely unaffected. The cell path reuses the
block's weather / soil / crop / signal snapshot and swaps only the imagery
``indices`` source to the cell's own mean (input-fidelity decision: cell
imagery, inherit the rest).

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | Sequence[str] | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_trees",
        sa.Column(
            "scope",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'block'"),
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_decision_trees_scope",
        "decision_trees",
        "scope IN ('block', 'cell')",
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint("ck_decision_trees_scope", "decision_trees", schema="public", type_="check")
    op.drop_column("decision_trees", "scope", schema="public")
