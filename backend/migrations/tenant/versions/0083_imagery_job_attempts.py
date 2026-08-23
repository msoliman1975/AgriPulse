"""imagery job `attempts` — so a stranded job can be retried a bounded number of times.

An imagery job that is picked up and then loses its worker stays in
``running`` for ever. Nothing recovers it:

* ``upsert_pending_ingestion_job`` is ``ON CONFLICT (subscription_id,
  scene_id) DO NOTHING``, so re-discovery cannot create the row again.
* the re-dispatch query selects ``WHERE status = 'pending'``, so a
  ``running`` row is never queued again.
* ``acquire_scene`` returns a no-op for any job whose status is not
  ``pending``, so even a hand-sent task does nothing.

Production had 7 such rows in one tenant on 2026-08-23, the oldest 575
hours old. Three of the seven blocks had no index rows at all for their
scene day while 35 sibling blocks on the same farm had a full set. So this
is missing data, not a stale status column.

``imagery.reap_stuck_jobs`` resets those rows to ``pending`` and dispatches
them again. That needs a bound, or a job that can never succeed is reset
every sweep for ever. ``attempts`` is that bound: the reaper increments it,
and a job that has used up its resets is marked ``failed`` with
``error_code = 'stuck_no_progress'`` so the failure detectors can see it.

The column counts *reaper* resets, not provider retries. A job that fails
normally is already terminal and is never reaped.

Both job tables get the column. Thermal has no block-path rows at all, so a
block-only change would leave the farm path unprotected — the same
farm-path gap that has been found in several other reads.

Revision ID: 0083
Revises: 0082
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | Sequence[str] | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Non-terminal statuses, repeated in the reaper's SQL. `requested` is not a
# value either table can hold today, but the detector's own SQL lists it, so
# the index covers it rather than diverging from the query it serves.
_NON_TERMINAL = "status IN ('pending', 'running', 'requested')"


def upgrade() -> None:
    for table in ("imagery_ingestion_jobs", "imagery_farm_ingestion_jobs"):
        op.add_column(
            table,
            sa.Column(
                "attempts",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    # The block table already has ix_imagery_ingestion_jobs_status_requested
    # on (status, requested_at), which serves the reaper. The farm table's
    # only status index is partial on 'pending', so the reaper would seq-scan
    # it. Give it the matching partial index.
    op.create_index(
        "ix_imagery_farm_jobs_stuck",
        "imagery_farm_ingestion_jobs",
        ["requested_at"],
        postgresql_where=sa.text(_NON_TERMINAL),
    )


def downgrade() -> None:
    op.drop_index("ix_imagery_farm_jobs_stuck", table_name="imagery_farm_ingestion_jobs")
    for table in ("imagery_farm_ingestion_jobs", "imagery_ingestion_jobs"):
        op.drop_column(table, "attempts")
