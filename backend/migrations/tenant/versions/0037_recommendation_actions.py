"""recommendations.actions — 4-horizon structured guidance (KB P1-B).

Adds a JSONB ``actions`` column to ``recommendations`` holding the
optional time-horizon guidance a decision-tree leaf may carry:
``{immediate|short_term|long_term|monitoring: [{text_en, text_ar}]}``.

Additive and back-compatible: defaults to ``'{}'`` so existing rows and
trees without an ``actions:`` block are unaffected — the single
``text_en`` summary remains the only guidance for those.

Revision ID: 0037
Revises: 0036
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037"
down_revision: str | Sequence[str] | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column(
            "actions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "actions")
