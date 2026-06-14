"""Decision-tree crop_path targeting.

Adds a nullable ``crop_path`` to ``public.decision_trees`` so a tree can
target a slice of the crop taxonomy by hierarchical path prefix:

  * ``mango``               → every Mango block (all varieties + strains)
  * ``mango.alphonso``      → all Alphonso strains
  * ``mango.alphonso.short``→ exactly Short Alphonso

A NULL ``crop_path`` falls back to the legacy ``crop_id`` match (or, when
both are NULL, the tree is crop-agnostic and always applies). ``crop_id``
stays populated (resolved from the path's first segment) so existing
display + crop-scoped queries keep working unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_trees",
        sa.Column("crop_path", sa.Text(), nullable=True),
        schema="public",
    )
    # Prefix-match lookups are text comparisons; a btree on crop_path keeps
    # the per-sweep tree-set fetch cheap as the catalog grows.
    op.create_index(
        "ix_decision_trees_crop_path",
        "decision_trees",
        ["crop_path"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_trees_crop_path", table_name="decision_trees", schema="public"
    )
    op.drop_column("decision_trees", "crop_path", schema="public")
