"""A per-block start date for heat units (D17).

The crop catalogue says where a crop starts counting heat: a calendar date,
planting, or entry into a stage (public 0112). A block whose season does not
follow its crop's rule, such as a late-pollinated orchard, can set its own
start date on its crop assignment; when set it wins over the crop's rule.

Nullable, no default: unset means "follow the crop".
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0109"
down_revision: str | Sequence[str] | None = "0108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE block_crops ADD COLUMN gdd_start_date date")


def downgrade() -> None:
    op.execute("ALTER TABLE block_crops DROP COLUMN IF EXISTS gdd_start_date")
