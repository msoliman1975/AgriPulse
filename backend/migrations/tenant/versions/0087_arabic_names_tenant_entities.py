"""Add an Arabic name to the tenant entities a user reads by name.

Four tenant tables name a thing with one free-text column and no Arabic
counterpart: `farms.name`, `blocks.name`, `resources.name` and
`vegetation_plans.name`. The Arabic interface therefore shows an English
farm name, an English block name and an English worker name on every
screen, no matter what language the person picked.

Each table gains a nullable `name_ar`. `farms` also gains
`description_ar`, because the farm description is shown next to the name
on the farm card and the farm detail header.

Nullable, not NOT NULL, for two reasons. A tenant that has no Arabic name
yet must still be able to create a farm, and the read path already has to
handle the fallback for rows written by an older API image during a
rolling deploy. Readers use `COALESCE(NULLIF(name_ar, ''), name)`.

The backfill copies the English value into `name_ar`. It is a placeholder,
not a translation: the platform cannot translate a tenant's own farm name,
and an empty Arabic column would show a blank name on the Arabic pages.
Mohamed edits these by hand afterwards.

Down drops the columns. No data outside them depends on the values.

Revision ID: 0087
Revises: 0086
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, source column to copy from)
_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    ("farms", "name_ar", "name"),
    ("farms", "description_ar", "description"),
    ("blocks", "name_ar", "name"),
    ("resources", "name_ar", "name"),
    ("vegetation_plans", "name_ar", "name"),
)


def upgrade() -> None:
    for table, column, source in _ADDITIONS:
        op.add_column(table, sa.Column(column, sa.Text(), nullable=True))
        # Seed the placeholder. `WHERE source IS NOT NULL` keeps a NULL
        # description NULL rather than turning it into an empty string.
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = {source} "  # noqa: S608
                f"WHERE {source} IS NOT NULL AND {column} IS NULL"
            )
        )


def downgrade() -> None:
    for table, column, _source in reversed(_ADDITIONS):
        op.drop_column(table, column)
