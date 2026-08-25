"""Rebuild `last_successful_ingest_at` from the imagery job rows.

The column used to be a wall-clock stamp written by a discovery poll that
queued at least one job. Two paths never wrote it:

* `imagery.backfill_scenes` / `imagery.backfill_farm_aoi_scenes` pass
  `bump_watermark=False`, so a one-shot historical load never stamped it.
* A live poll stamped it only when it created a job, so a subscription whose
  backfill already covered every published scene stayed NULL until the next
  new pass arrived.

Prod, tenant_01a025a4dd677d30ba14da3993df4a36, 2026-08-25: the Mango Republic
Sentinel-2 subscription had 216 succeeded jobs, the newest scene sensed on
20 August, and a NULL watermark. `_resolve_discovery_window` reads NULL as a
cold start, so that subscription searched a 90-day catalogue window every day
and read back 27 scenes it already held.

The application now derives the column: it means the sensing time of the
newest scene the subscription has successfully ingested, and it is rewritten
inside the same transaction that marks a job `succeeded`. This backfills the
same value for rows that already exist, so a subscription does not have to
wait for its next success to become correct.

Down restores nothing. The old value was a poll timestamp with no separate
record anywhere, so it cannot be recovered, and the derived value is a
superset of what it meant. Down is a no-op on purpose.

Revision ID: 0086
Revises: 0085
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BLOCK = """
    UPDATE imagery_aoi_subscriptions s
       SET last_successful_ingest_at = j.newest
      FROM (
            SELECT subscription_id, max(scene_datetime) AS newest
              FROM imagery_ingestion_jobs
             WHERE status = 'succeeded'
             GROUP BY subscription_id
      ) j
     WHERE j.subscription_id = s.id
       AND s.last_successful_ingest_at IS DISTINCT FROM j.newest
"""

_FARM = """
    UPDATE imagery_farm_subscriptions s
       SET last_successful_ingest_at = j.newest,
           updated_at = now()
      FROM (
            SELECT subscription_id, max(scene_datetime) AS newest
              FROM imagery_farm_ingestion_jobs
             WHERE status = 'succeeded'
             GROUP BY subscription_id
      ) j
     WHERE j.subscription_id = s.id
       AND s.last_successful_ingest_at IS DISTINCT FROM j.newest
"""


def upgrade() -> None:
    op.execute(_BLOCK)
    op.execute(_FARM)


def downgrade() -> None:
    """No-op. See the module docstring."""
