"""Crop-scoped signals and scout forms (decision D21).

Adds ``crop_paths text[]`` to ``public.signal_definitions`` and
``public.signal_templates``. An empty array (the default, and every existing
row) means "all crops", so nothing changes for today's catalog. A non-empty
array names crop paths (``date_palm``, ``date_palm.medjool``); a definition
then switches on automatically for every block whose current crop path equals
one of them or sits below it, with no manual assignment (see
``signals/snapshot.py``). A ``GIN`` index serves the ``&&``/``@>`` lookups the
catalog filter uses.

The Medjool ``date_`` signals of public 0098 are scoped to
``date_palm.medjool`` in the migration that seeds the v2 signals, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0102"
down_revision: str | Sequence[str] | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("signal_definitions", "signal_templates")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "crop_paths",
                postgresql.ARRAY(sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::text[]"),
            ),
            schema="public",
        )
        op.create_index(
            f"ix_{table}_crop_paths",
            table,
            ["crop_paths"],
            schema="public",
            postgresql_using="gin",
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_crop_paths", table_name=table, schema="public")
        op.drop_column(table, "crop_paths", schema="public")
