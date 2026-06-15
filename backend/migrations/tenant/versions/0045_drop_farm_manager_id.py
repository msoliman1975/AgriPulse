"""U-4a (identity unification) — drop the dead farms.farm_manager_id column.

`farm_manager_id` was added in migration 0027 (farm-block-config PR-1) but
never wired: it isn't writable (not in the create path or the update
allowlist), never returned in any response, has no UI, and is read nowhere.
U-4a replaces it with a derived, read-only `farm_manager` on FarmResponse,
resolved from the active `FarmManager` farm-scope (the canonical source of
"who manages this farm"). This migration drops the redundant column.

Reversible: downgrade re-adds the nullable column (empty — the value was
inert, so nothing is lost).

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("farms", "farm_manager_id")


def downgrade() -> None:
    op.add_column(
        "farms",
        sa.Column("farm_manager_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
