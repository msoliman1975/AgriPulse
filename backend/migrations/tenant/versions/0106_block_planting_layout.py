"""A block records its planting layout: row spacing, in-row spacing, plant count (D23).

The crop catalogue holds the expected layout as reference values (manual 1.7,
3.1 #7: Medjool at 10 x 8 m or 9 x 9 m); this is what was actually planted on
the block. All three are optional, so existing blocks are untouched. Densities
are derived when read, never stored.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0106"
down_revision: str | Sequence[str] | None = "0105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE blocks
            ADD COLUMN row_spacing_m numeric(6, 2),
            ADD COLUMN in_row_spacing_m numeric(6, 2),
            ADD COLUMN plant_count integer,
            ADD CONSTRAINT ck_blocks_row_spacing_m
                CHECK (row_spacing_m IS NULL OR row_spacing_m > 0),
            ADD CONSTRAINT ck_blocks_in_row_spacing_m
                CHECK (in_row_spacing_m IS NULL OR in_row_spacing_m > 0),
            ADD CONSTRAINT ck_blocks_plant_count
                CHECK (plant_count IS NULL OR plant_count >= 0);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE blocks
            DROP CONSTRAINT IF EXISTS ck_blocks_plant_count,
            DROP CONSTRAINT IF EXISTS ck_blocks_in_row_spacing_m,
            DROP CONSTRAINT IF EXISTS ck_blocks_row_spacing_m,
            DROP COLUMN IF EXISTS plant_count,
            DROP COLUMN IF EXISTS in_row_spacing_m,
            DROP COLUMN IF EXISTS row_spacing_m;
        """
    )
