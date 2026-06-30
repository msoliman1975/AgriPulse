"""Add ``farms.country_code`` — logical ref to public.countries.code.

Decision-Tree multi-axis targeting (PR-1) needs a controlled location on each
farm. Blocks inherit country via their parent farm. Like ``block_crops``'s
reference to ``public.crops``, this is a *logical* cross-schema reference: no
DB FK (search_path / cross-schema constraints don't compose cleanly), the
service layer validates the code against the catalog on write.

Backfill: existing farms are stamped ``'EG'`` (Egypt) so they keep matching
country-filtered trees once those land — the targeting guardrail in the
proposal. Tenants operating elsewhere can re-point individual farms via the
farm-edit endpoint afterwards.

Revision ID: 0051
Revises: 0050
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("farms", sa.Column("country_code", sa.Text(), nullable=True))
    # Default existing farms to Egypt (see module docstring).
    op.execute("UPDATE farms SET country_code = 'EG' WHERE country_code IS NULL")
    op.create_check_constraint(
        "ck_farms_country_code_upper",
        "farms",
        "country_code IS NULL OR country_code = upper(country_code)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_farms_country_code_upper", "farms", type_="check")
    op.drop_column("farms", "country_code")
