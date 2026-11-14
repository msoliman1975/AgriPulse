"""A block's salinity class gains FAO's fifth class, very strongly saline (D18).

Manual 1.7, 4.1 #7 gives FAO's soil salinity classes by ECe: non-saline
0-2, slightly saline 2-4, moderately saline 4-8, strongly saline 8-16 and
very strongly saline above 16 dS/m. The check constraint allowed only the
first four, so a block above 16 dS/m had to be recorded as strongly saline.

Downgrade folds very strongly saline back into strongly saline, the nearest
class the old constraint allows, before restoring it.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0105"
down_revision: str | Sequence[str] | None = "0104"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE blocks DROP CONSTRAINT IF EXISTS ck_blocks_salinity_class;
        ALTER TABLE blocks ADD CONSTRAINT ck_blocks_salinity_class CHECK (
            salinity_class IS NULL OR salinity_class IN (
                'non_saline', 'slightly_saline', 'moderately_saline',
                'strongly_saline', 'very_strongly_saline'
            )
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE blocks SET salinity_class = 'strongly_saline'
            WHERE salinity_class = 'very_strongly_saline';
        ALTER TABLE blocks DROP CONSTRAINT IF EXISTS ck_blocks_salinity_class;
        ALTER TABLE blocks ADD CONSTRAINT ck_blocks_salinity_class CHECK (
            salinity_class IS NULL OR salinity_class IN (
                'non_saline', 'slightly_saline', 'moderately_saline', 'strongly_saline'
            )
        );
        """
    )
