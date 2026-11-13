"""Title on plan activities (Agri Operation PR 1).

Operation manual activities now carry an English and Arabic title (public
0104). Applying a manual copies them onto ``plan_activities`` so the Plan
board can show what the work is, not only its type. Nullable; manual board
activities keep showing their type. Additive only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0101"
down_revision: str | Sequence[str] | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_activities", sa.Column("title", sa.Text()))
    op.add_column("plan_activities", sa.Column("title_ar", sa.Text()))


def downgrade() -> None:
    op.drop_column("plan_activities", "title_ar")
    op.drop_column("plan_activities", "title")
