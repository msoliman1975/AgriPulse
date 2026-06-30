"""Per-cell recommendation/alert outputs (per-cell PR-C2).

Adds a nullable ``cell_id`` to ``recommendations``, ``recommendations_history``
and ``alerts`` so a cell-scoped decision tree (PR-C1) can attribute its output
to a specific sub-block grid cell. ``cell_id`` is a logical reference to
``grid_cells.id`` (no FK — like ``block_grid_aggregates.cell_id`` — so a grid
rezone never blocks on dependent recommendation rows); block-scoped output
leaves it NULL.

Idempotency: the open-state dedup splits into two partial unique indexes so a
block-scoped rec (cell_id NULL) still dedups on ``(block_id, tree_id)`` while a
cell-scoped rec dedups per cell on ``(block_id, cell_id, tree_id)``. A single
index can't do both because NULLs compare distinct. Alerts keep their existing
``(block_id, rule_code)`` dedup — PR-C3 embeds the cell id in the synthesised
rule_code, so cells separate naturally there.

Revision ID: 0052
Revises: 0051
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052"
down_revision: str | Sequence[str] | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("recommendations", "recommendations_history", "alerts"):
        op.add_column(
            table,
            sa.Column("cell_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    # Split the open-state idempotency: block-scoped (cell_id NULL) keeps the
    # old key; cell-scoped (cell_id NOT NULL) dedups per cell.
    op.drop_index("uq_recommendations_block_tree_open", table_name="recommendations")
    op.create_index(
        "uq_recommendations_block_tree_open",
        "recommendations",
        ["block_id", "tree_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND cell_id IS NULL"),
    )
    op.create_index(
        "uq_recommendations_cell_tree_open",
        "recommendations",
        ["block_id", "cell_id", "tree_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open' AND cell_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_recommendations_cell_tree_open", table_name="recommendations")
    op.drop_index("uq_recommendations_block_tree_open", table_name="recommendations")
    op.create_index(
        "uq_recommendations_block_tree_open",
        "recommendations",
        ["block_id", "tree_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )
    for table in ("alerts", "recommendations_history", "recommendations"):
        op.drop_column(table, "cell_id")
