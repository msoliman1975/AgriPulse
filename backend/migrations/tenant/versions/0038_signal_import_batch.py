"""signals.import_batch_id — track which CSV upload created an observation.

Adds a nullable ``import_batch_id`` UUID to ``signal_observations`` so a
whole CSV upload can be listed and undone as a unit (the route assigns
one fresh ``import_batch_id`` per upload). A partial index keyed on the
column (only where it IS NOT NULL) keeps the list/delete-by-batch
lookups cheap without bloating the hypertable's existing chunks for the
single-shot observations that carry no batch.

Additive and back-compatible: the column is nullable so existing rows
and the non-CSV record path are unaffected. Downgrade just drops the
index then the column (data-safe — no existing data depends on it).

Revision ID: 0038
Revises: 0037
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038"
down_revision: str | Sequence[str] | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "signal_observations",
        sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        "CREATE INDEX ix_signal_observations_import_batch "
        "ON signal_observations (import_batch_id) "
        "WHERE import_batch_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_signal_observations_import_batch")
    op.drop_column("signal_observations", "import_batch_id")
