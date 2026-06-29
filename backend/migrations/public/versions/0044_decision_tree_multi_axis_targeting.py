"""Decision-tree multi-axis targeting columns (DT targeting PR-2).

Extends ``public.decision_trees`` from single-crop targeting to three
multi-value axes:

  * ``crop_paths``    text[] — hierarchical taxonomy prefixes (supersedes the
                               single ``crop_path``; that column stays for
                               back-compat display + legacy reads).
  * ``country_codes`` text[] — ISO 3166-1 alpha-2 codes (public.countries).
  * ``soil_textures`` text[] — block soil-texture enum values.

Matching semantics (the PR-3 engine matcher): a block matches a tree iff, for
each axis, the tree's set is empty (= matches any) OR the block's value is in
the set. So an all-empty tree keeps matching every block — legacy trees and
crop-agnostic platform trees are unaffected.

Backfill: existing single ``crop_path`` values seed ``crop_paths``. The other
two axes default empty (= any), so behaviour is unchanged until an author
narrows a tree.

Revision ID: 0044
Revises: 0043
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | Sequence[str] | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AXES = ("crop_paths", "country_codes", "soil_textures")


def upgrade() -> None:
    for col in _AXES:
        op.add_column(
            "decision_trees",
            sa.Column(
                col,
                postgresql.ARRAY(sa.Text()),
                nullable=False,
                server_default=sa.text("ARRAY[]::text[]"),
            ),
            schema="public",
        )
    # Seed crop_paths from the legacy single crop_path.
    op.execute(
        "UPDATE public.decision_trees "
        "SET crop_paths = ARRAY[crop_path] "
        "WHERE crop_path IS NOT NULL AND crop_path <> ''"
    )
    # GIN indexes so the per-sweep matcher's array-membership tests stay cheap
    # as the catalog grows.
    for col in _AXES:
        op.create_index(
            f"ix_decision_trees_{col}",
            "decision_trees",
            [col],
            schema="public",
            postgresql_using="gin",
        )


def downgrade() -> None:
    for col in _AXES:
        op.drop_index(f"ix_decision_trees_{col}", table_name="decision_trees", schema="public")
        op.drop_column("decision_trees", col, schema="public")
