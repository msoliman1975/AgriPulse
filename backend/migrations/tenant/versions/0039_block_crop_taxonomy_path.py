"""block_crops: crop_variety_strain_id + denormalized crop_path.

Carries the deepest assigned taxonomy node (``crop_variety_strain_id``,
a logical cross-schema ref to ``public.crop_variety_strains``) and the
canonical hierarchical path (``crop_path``, e.g. ``mango.alphonso.short``
or just ``cotton``) used by consumers (reports/trees/recommendations)
to filter and group by prefix.

Backfill: existing rows get their path from the variety (if set) else
the crop code — no existing assignment carried a strain. Additive and
back-compatible; downgrade drops the column + index (data-safe).

Revision ID: 0039
Revises: 0038
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "block_crops",
        sa.Column("crop_variety_strain_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "block_crops",
        sa.Column("crop_path", sa.Text(), nullable=False, server_default=""),
    )
    # Backfill: variety path when a variety is set, else the crop code.
    op.execute(
        """
        UPDATE block_crops bc
           SET crop_path = COALESCE(
               (SELECT v.path FROM public.crop_varieties v WHERE v.id = bc.crop_variety_id),
               (SELECT c.code FROM public.crops c WHERE c.id = bc.crop_id),
               ''
           )
        """
    )
    op.execute(
        "CREATE INDEX ix_block_crops_crop_path ON block_crops (crop_path) " "WHERE crop_path <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_block_crops_crop_path")
    op.drop_column("block_crops", "crop_path")
    op.drop_column("block_crops", "crop_variety_strain_id")
