"""The manual as a saved plan last applied it (Agri Operation PR 4).

``plan_allocations.manual_snapshot`` holds the manual's activities, keyed by
code, at the moment the saved plan was last applied. When the manual is
published again, the farm sees what changed against this snapshot before it
re-applies (decision B4). Additive only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0103"
down_revision: str | Sequence[str] | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plan_allocations", sa.Column("manual_snapshot", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("plan_allocations", "manual_snapshot")
