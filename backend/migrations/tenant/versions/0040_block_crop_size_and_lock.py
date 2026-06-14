"""block_crops: canopy_size_class + growth_stage_locked.

Per-planting canopy size pick (validated in app code against the crop's
resolved ``size_classes`` lookup) and a flag that exempts the block from
the phenology auto-advance task (manual stage stays authoritative).

Both nullable/defaulted -> data-safe; downgrade drops the columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("block_crops", sa.Column("canopy_size_class", sa.Text(), nullable=True))
    op.add_column(
        "block_crops",
        sa.Column(
            "growth_stage_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("block_crops", "growth_stage_locked")
    op.drop_column("block_crops", "canopy_size_class")
