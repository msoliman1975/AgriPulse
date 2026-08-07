"""Rewrite the integration-health views without the join fan-out.

`v_block_integration_health` / `v_farm_integration_health` were built as
one flat SELECT that LEFT JOINs a block out to *two independent*
one-to-many branches and then de-duplicates after the fact with
`COUNT(DISTINCT ...)`:

    blocks -> weather_subscriptions -> weather_ingestion_attempts (wa_failed)
                                    -> weather_ingestion_attempts (wa_running)
           -> imagery_aoi_subscriptions -> imagery_ingestion_jobs

Every branch multiplies against every other, so the row count the planner
has to materialise before aggregating is

    weather_attempts x weather_attempts x imagery_jobs   (per block)

i.e. quadratic in ingestion attempts and linear in ingestion jobs. It was
invisible while those two tables were near-empty. Measured on prod
2026-08-05 against the 36-block Bashier Elkhier farm, once ~2 months of
ingestion history had accumulated (26 attempts + 192 jobs per
subscription):

    26 * 26 * 192 = 129,792 rows per block
    x 36 blocks   = 4,672,512 rows collapsed down to 36 output rows

    v_block_integration_health (36 blocks)  ->  7,280 ms
    v_farm_integration_health  (whole tenant) -> 10,418 ms

with a 28 MB external merge sort spilling to disk (work_mem is 4 MB).
The block view sits in the Farm Console's blocking load fan-out, so that
7 s was the floor on "open a farm".

The fix is to collapse each branch to one row per block *before* joining
anything, so no branch can multiply against another. Same columns, same
types, same order, same values — `COUNT(DISTINCT x.id) FILTER (...)` over
a fanned-out join is by construction equal to `count(*) FILTER (...)`
over the un-fanned branch, because each row of a branch belongs to
exactly one block.

    v_block_integration_health  ->  8.8 ms   (~830x)

`v_farm_integration_health` becomes a plain SUM/MAX rollup of the block
view rather than a second copy of the same joins: every count column is
additive across the blocks of a farm (a subscription belongs to exactly
one block) and every timestamp column is a MAX. That also makes the two
views incapable of disagreeing.

Note `SUM()` over `bigint` returns `numeric`, so the farm rollup casts
back to `bigint` to keep the column types identical to the pre-existing
`COUNT()`-derived ones.

The views are dropped and recreated rather than CREATE OR REPLACE'd:
the farm view now depends on the block view, so the two have to be
rebuilt in dependency order.

Revision ID: 0056
Revises: 0055
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror app.core.settings defaults; see migration 0022 for why hard-coding
# in the view is acceptable (snapshot of state, not behavioural policy).
_DEFAULT_WEATHER_CADENCE_HOURS = 3
_DEFAULT_IMAGERY_CADENCE_HOURS = 24

# ---------------------------------------------------------------------------
# New (fan-out free) definitions
# ---------------------------------------------------------------------------

_BLOCK_VIEW_FAST = f"""
    CREATE VIEW v_block_integration_health AS
    WITH ws_agg AS (
        SELECT
            ws.block_id,
            count(*) FILTER (WHERE ws.is_active) AS weather_active_subs,
            max(ws.last_successful_ingest_at) AS weather_last_sync_at,
            max(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            count(*) FILTER
              (WHERE ws.is_active
                AND (ws.last_successful_ingest_at IS NULL
                     OR ws.last_successful_ingest_at <
                        now() - make_interval(
                          hours => COALESCE(ws.cadence_hours,
                                            {_DEFAULT_WEATHER_CADENCE_HOURS}))))
              AS weather_overdue_count
        FROM weather_subscriptions ws
        GROUP BY ws.block_id
    ),
    wa_agg AS (
        SELECT
            ws.block_id,
            count(*) FILTER
              (WHERE wa.status = 'failed'
                AND wa.started_at > now() - interval '24 hours')
              AS weather_failed_24h,
            count(*) FILTER (WHERE wa.status = 'running')
              AS weather_running_count
        FROM weather_ingestion_attempts wa
        JOIN weather_subscriptions ws ON ws.id = wa.subscription_id
        GROUP BY ws.block_id
    ),
    ias_agg AS (
        SELECT
            ias.block_id,
            count(*) FILTER (WHERE ias.is_active) AS imagery_active_subs,
            count(*) FILTER
              (WHERE ias.is_active
                AND (ias.last_attempted_at IS NULL
                     OR ias.last_attempted_at <
                        now() - make_interval(
                          hours => COALESCE(ias.cadence_hours,
                                            {_DEFAULT_IMAGERY_CADENCE_HOURS}))))
              AS imagery_overdue_count
        FROM imagery_aoi_subscriptions ias
        GROUP BY ias.block_id
    ),
    ij_agg AS (
        SELECT
            ias.block_id,
            max(ij.requested_at) AS imagery_last_sync_at,
            count(*) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h,
            count(*) FILTER
              (WHERE ij.status IN ('pending', 'requested', 'running'))
              AS imagery_running_count
        FROM imagery_ingestion_jobs ij
        JOIN imagery_aoi_subscriptions ias ON ias.id = ij.subscription_id
        GROUP BY ias.block_id
    )
    SELECT
        b.id      AS block_id,
        b.farm_id AS farm_id,
        b.name    AS block_name,
        COALESCE(ws_agg.weather_active_subs, 0)::bigint   AS weather_active_subs,
        ws_agg.weather_last_sync_at                       AS weather_last_sync_at,
        ws_agg.weather_last_failed_at                     AS weather_last_failed_at,
        COALESCE(ias_agg.imagery_active_subs, 0)::bigint  AS imagery_active_subs,
        ij_agg.imagery_last_sync_at                       AS imagery_last_sync_at,
        COALESCE(ij_agg.imagery_failed_24h, 0)::bigint    AS imagery_failed_24h,
        COALESCE(wa_agg.weather_failed_24h, 0)::bigint    AS weather_failed_24h,
        COALESCE(wa_agg.weather_running_count, 0)::bigint AS weather_running_count,
        COALESCE(ij_agg.imagery_running_count, 0)::bigint AS imagery_running_count,
        COALESCE(ws_agg.weather_overdue_count, 0)::bigint AS weather_overdue_count,
        COALESCE(ias_agg.imagery_overdue_count, 0)::bigint AS imagery_overdue_count
    FROM blocks b
    LEFT JOIN ws_agg  ON ws_agg.block_id  = b.id
    LEFT JOIN wa_agg  ON wa_agg.block_id  = b.id
    LEFT JOIN ias_agg ON ias_agg.block_id = b.id
    LEFT JOIN ij_agg  ON ij_agg.block_id  = b.id
    WHERE b.deleted_at IS NULL
"""

# Rollup of the block view. Every count is additive across a farm's blocks
# (a subscription/attempt/job belongs to exactly one block) and every
# timestamp is a MAX, so this is value-identical to the old independent
# farm-level join — and cannot drift from the block view.
_FARM_VIEW_FAST = """
    CREATE VIEW v_farm_integration_health AS
    SELECT
        f.id   AS farm_id,
        f.name AS farm_name,
        COALESCE(sum(h.weather_active_subs), 0)::bigint   AS weather_active_subs,
        max(h.weather_last_sync_at)                       AS weather_last_sync_at,
        max(h.weather_last_failed_at)                     AS weather_last_failed_at,
        COALESCE(sum(h.imagery_active_subs), 0)::bigint   AS imagery_active_subs,
        max(h.imagery_last_sync_at)                       AS imagery_last_sync_at,
        COALESCE(sum(h.imagery_failed_24h), 0)::bigint    AS imagery_failed_24h,
        COALESCE(sum(h.weather_failed_24h), 0)::bigint    AS weather_failed_24h,
        COALESCE(sum(h.weather_running_count), 0)::bigint AS weather_running_count,
        COALESCE(sum(h.imagery_running_count), 0)::bigint AS imagery_running_count,
        COALESCE(sum(h.weather_overdue_count), 0)::bigint AS weather_overdue_count,
        COALESCE(sum(h.imagery_overdue_count), 0)::bigint AS imagery_overdue_count
    FROM farms f
    LEFT JOIN v_block_integration_health h ON h.farm_id = f.id
    WHERE f.deleted_at IS NULL
    GROUP BY f.id, f.name
"""

# ---------------------------------------------------------------------------
# Previous (fanned-out) definitions — reproduced verbatim from 0042 so the
# downgrade restores exactly what was there before.
# ---------------------------------------------------------------------------

_FARM_VIEW_LEGACY = f"""
    CREATE VIEW v_farm_integration_health AS
    SELECT
        f.id   AS farm_id,
        f.name AS farm_name,
        COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
          AS weather_active_subs,
        MAX(ws.last_successful_ingest_at)
          AS weather_last_sync_at,
        MAX(ws.last_attempted_at) FILTER
          (WHERE ws.last_attempted_at >
                 COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
          AS weather_last_failed_at,
        COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
          AS imagery_active_subs,
        MAX(ij.requested_at)
          AS imagery_last_sync_at,
        COUNT(DISTINCT ij.id) FILTER
          (WHERE ij.status = 'failed'
            AND ij.requested_at > now() - interval '24 hours')
          AS imagery_failed_24h,
        COUNT(DISTINCT wa_failed.id) FILTER
          (WHERE wa_failed.status = 'failed'
            AND wa_failed.started_at > now() - interval '24 hours')
          AS weather_failed_24h,
        COUNT(DISTINCT wa_running.id) FILTER
          (WHERE wa_running.status = 'running')
          AS weather_running_count,
        COUNT(DISTINCT ij.id) FILTER
          (WHERE ij.status IN ('pending', 'requested', 'running'))
          AS imagery_running_count,
        COUNT(DISTINCT ws.id) FILTER
          (WHERE ws.is_active
            AND (ws.last_successful_ingest_at IS NULL
                 OR ws.last_successful_ingest_at <
                    now() - make_interval(
                      hours => COALESCE(ws.cadence_hours,
                                        {_DEFAULT_WEATHER_CADENCE_HOURS}))))
          AS weather_overdue_count,
        COUNT(DISTINCT ias.id) FILTER
          (WHERE ias.is_active
            AND (ias.last_attempted_at IS NULL
                 OR ias.last_attempted_at <
                    now() - make_interval(
                      hours => COALESCE(ias.cadence_hours,
                                        {_DEFAULT_IMAGERY_CADENCE_HOURS}))))
          AS imagery_overdue_count
    FROM farms f
    LEFT JOIN blocks b
      ON b.farm_id = f.id AND b.deleted_at IS NULL
    LEFT JOIN weather_subscriptions ws
      ON ws.block_id = b.id
    LEFT JOIN imagery_aoi_subscriptions ias
      ON ias.block_id = b.id
    LEFT JOIN imagery_ingestion_jobs ij
      ON ij.subscription_id = ias.id
    LEFT JOIN weather_ingestion_attempts wa_failed
      ON wa_failed.subscription_id = ws.id
    LEFT JOIN weather_ingestion_attempts wa_running
      ON wa_running.subscription_id = ws.id
    WHERE f.deleted_at IS NULL
    GROUP BY f.id, f.name
"""

_BLOCK_VIEW_LEGACY = f"""
    CREATE VIEW v_block_integration_health AS
    SELECT
        b.id      AS block_id,
        b.farm_id AS farm_id,
        b.name    AS block_name,
        COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
          AS weather_active_subs,
        MAX(ws.last_successful_ingest_at)
          AS weather_last_sync_at,
        MAX(ws.last_attempted_at) FILTER
          (WHERE ws.last_attempted_at >
                 COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
          AS weather_last_failed_at,
        COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
          AS imagery_active_subs,
        MAX(ij.requested_at)
          AS imagery_last_sync_at,
        COUNT(DISTINCT ij.id) FILTER
          (WHERE ij.status = 'failed'
            AND ij.requested_at > now() - interval '24 hours')
          AS imagery_failed_24h,
        COUNT(DISTINCT wa_failed.id) FILTER
          (WHERE wa_failed.status = 'failed'
            AND wa_failed.started_at > now() - interval '24 hours')
          AS weather_failed_24h,
        COUNT(DISTINCT wa_running.id) FILTER
          (WHERE wa_running.status = 'running')
          AS weather_running_count,
        COUNT(DISTINCT ij.id) FILTER
          (WHERE ij.status IN ('pending', 'requested', 'running'))
          AS imagery_running_count,
        COUNT(DISTINCT ws.id) FILTER
          (WHERE ws.is_active
            AND (ws.last_successful_ingest_at IS NULL
                 OR ws.last_successful_ingest_at <
                    now() - make_interval(
                      hours => COALESCE(ws.cadence_hours,
                                        {_DEFAULT_WEATHER_CADENCE_HOURS}))))
          AS weather_overdue_count,
        COUNT(DISTINCT ias.id) FILTER
          (WHERE ias.is_active
            AND (ias.last_attempted_at IS NULL
                 OR ias.last_attempted_at <
                    now() - make_interval(
                      hours => COALESCE(ias.cadence_hours,
                                        {_DEFAULT_IMAGERY_CADENCE_HOURS}))))
          AS imagery_overdue_count
    FROM blocks b
    LEFT JOIN weather_subscriptions ws
      ON ws.block_id = b.id
    LEFT JOIN imagery_aoi_subscriptions ias
      ON ias.block_id = b.id
    LEFT JOIN imagery_ingestion_jobs ij
      ON ij.subscription_id = ias.id
    LEFT JOIN weather_ingestion_attempts wa_failed
      ON wa_failed.subscription_id = ws.id
    LEFT JOIN weather_ingestion_attempts wa_running
      ON wa_running.subscription_id = ws.id
    WHERE b.deleted_at IS NULL
    GROUP BY b.id, b.farm_id, b.name
"""


def _drop_both() -> None:
    # Farm first: after this migration it depends on the block view.
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute("DROP VIEW IF EXISTS v_block_integration_health")


def upgrade() -> None:
    _drop_both()
    op.execute(_BLOCK_VIEW_FAST)
    op.execute(_FARM_VIEW_FAST)


def downgrade() -> None:
    _drop_both()
    op.execute(_BLOCK_VIEW_LEGACY)
    op.execute(_FARM_VIEW_LEGACY)
