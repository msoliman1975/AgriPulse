"""Arabic notes on plan activities (D26).

Operation manual activities carry ``notes_ar`` beside ``notes`` (public
0104), and a saved plan's activity edits can carry it too. Applying a manual
copied the English notes onto ``plan_activities`` and dropped the Arabic, so
the Plan board showed English notes to an Arabic reader. This adds the column
the apply path now fills. Nullable; manual board activities have none.
Additive only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0108"
down_revision: str | Sequence[str] | None = "0107"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_activities", sa.Column("notes_ar", sa.Text()))


def downgrade() -> None:
    op.drop_column("plan_activities", "notes_ar")
