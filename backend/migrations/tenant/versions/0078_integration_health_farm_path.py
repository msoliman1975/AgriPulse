"""Integration health must see the FARM acquisition path, not just blocks.

Every view behind the Integration Health page was written when a
subscription was necessarily per-block. Since 0074/0076/0077 a farm can
subscribe on its own behalf — `weather_farm_subscriptions`,
`imagery_farm_subscriptions` + `imagery_farm_ingestion_jobs`, and
farm-scoped rows in `weather_ingestion_attempts` (`block_id IS NULL`) —
and none of those tables is read anywhere in this file's ancestors. The
page whose entire job is to say whether ingestion is working is blind to
the path that is now doing the ingesting.

Measured on prod (`tenant_019eafdc242c7320948e13490efc67dd`, 2026-08-17):

  Green Farm [Demo-01]   1 active weather farm sub (synced 06:17 today)
                         2 active imagery farm subs, both fetch_farm_aoi
                         65 farm ingestion jobs, 9 succeeded thermal
                         0 block subscriptions
    -> v_farm_integration_health says: 0 weather subs, 0 imagery subs,
       last sync NULL, 0 failures. A farm ingesting an hour ago reads as
       never configured.

  Bashier Elkhier        weather farm sub synced 2026-08-17 06:17
    -> the view reports 2026-08-13 17:38, four days stale, because it
       maxes only over the abandoned per-block rows. The inverse
       failure: a false alarm on a healthy farm.

Both directions are worse than no page at all, because an operator
believes it.

Three changes, all read-side:

* `v_farm_integration_health` stops being a pure rollup of the block view
  and adds the farm-level rows on top. Counts add, timestamps take the
  later of the two paths. It cannot go back to being a plain rollup while
  a farm carries subscriptions of its own.

* `v_integration_recent_attempts` gains a third UNION arm for
  `imagery_farm_ingestion_jobs`. Without it, 91 farm jobs in the last 14
  days on that one tenant — including 50 pending and 2 running — are
  absent from the Runs tab, from the per-farm drill-down, and from
  `streak_watcher`, which reads this view and therefore could never alert
  on a farm-path failure streak. Thermal (`landsat_c2_l2_st`) is
  farm-AOI only by construction, so *no* thermal ingestion has ever been
  visible in the Runs tab.

* Both attempt-shaped views gain a `scope` column ('block' | 'farm').
  Callers were distinguishing the two by `block_id IS NULL`, which is
  the same test but leaves the API returning a bare null and the UI
  printing an empty cell. Naming it lets the row say "whole farm".

Deliberately unchanged: `v_block_integration_health`. A block has no
farm-level subscription of its own, and attributing a farm's fetch to
each of its blocks is exactly the 36-attempts-for-one-HTTP-call
duplication that 0077 removed.

Which imagery farm subscriptions count: only `fetch_farm_aoi` ones.
0074 gave every farm a row whether or not it fetches anything, and
counting a `fetch_farm_aoi = false` row as an active subscription would
have moved B-Elkair-Suez from 36 to 37 while nothing about its
acquisition changed. That flag is what decides whether the row does
anything at all (#496), and it is the same predicate the queue scan in
`service.list_queue` already uses. Weather has no such flag — a farm
weather row is authoritative on its own — so every active one counts.

Revision ID: 0078
Revises: 0077
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror app.core.settings defaults; see migration 0022 for why hard-coding
# these in the view body is acceptable (a snapshot of state, not policy).
_DEFAULT_WEATHER_CADENCE_HOURS = 3
_DEFAULT_IMAGERY_CADENCE_HOURS = 24


# ---------------------------------------------------------------------------
# v_farm_integration_health — block rollup + the farm's own rows
# ---------------------------------------------------------------------------

_FARM_VIEW_BOTH_PATHS = f"""
    CREATE VIEW v_farm_integration_health AS
    WITH block_roll AS (
        SELECT
            h.farm_id,
            sum(h.weather_active_subs)   AS weather_active_subs,
            max(h.weather_last_sync_at)  AS weather_last_sync_at,
            max(h.weather_last_failed_at) AS weather_last_failed_at,
            sum(h.imagery_active_subs)   AS imagery_active_subs,
            max(h.imagery_last_sync_at)  AS imagery_last_sync_at,
            sum(h.imagery_failed_24h)    AS imagery_failed_24h,
            sum(h.weather_failed_24h)    AS weather_failed_24h,
            sum(h.weather_running_count) AS weather_running_count,
            sum(h.imagery_running_count) AS imagery_running_count,
            sum(h.weather_overdue_count) AS weather_overdue_count,
            sum(h.imagery_overdue_count) AS imagery_overdue_count
        FROM v_block_integration_health h
        GROUP BY h.farm_id
    ),
    -- One row per (farm, provider). Authoritative on its own: unlike
    -- imagery there is no per-farm opt-in flag, because a weather fetch
    -- has always been one call at the farm centroid.
    wfs_agg AS (
        SELECT
            wfs.farm_id,
            count(*) FILTER (WHERE wfs.is_active) AS active_subs,
            max(wfs.last_successful_ingest_at) AS last_sync_at,
            max(wfs.last_attempted_at) FILTER
              (WHERE wfs.last_attempted_at >
                     COALESCE(wfs.last_successful_ingest_at, '-infinity'::timestamptz))
              AS last_failed_at,
            count(*) FILTER
              (WHERE wfs.is_active
                AND (wfs.last_successful_ingest_at IS NULL
                     OR wfs.last_successful_ingest_at <
                        now() - make_interval(
                          hours => COALESCE(wfs.cadence_hours,
                                            {_DEFAULT_WEATHER_CADENCE_HOURS}))))
              AS overdue_count
        FROM weather_farm_subscriptions wfs
        WHERE wfs.deleted_at IS NULL
        GROUP BY wfs.farm_id
    ),
    -- `block_id IS NULL` is what makes an attempt farm-scoped (0077). The
    -- block half of these same counts already lives in the block view, so
    -- filtering here is what keeps the two from double-counting.
    wfa_agg AS (
        SELECT
            wa.farm_id,
            count(*) FILTER
              (WHERE wa.status = 'failed'
                AND wa.started_at > now() - interval '24 hours')
              AS failed_24h,
            count(*) FILTER (WHERE wa.status = 'running') AS running_count
        FROM weather_ingestion_attempts wa
        WHERE wa.block_id IS NULL
        GROUP BY wa.farm_id
    ),
    ifs_agg AS (
        SELECT
            ifs.farm_id,
            count(*) FILTER (WHERE ifs.is_active AND ifs.fetch_farm_aoi)
              AS active_subs,
            count(*) FILTER
              (WHERE ifs.is_active
                AND ifs.fetch_farm_aoi
                AND (ifs.last_attempted_at IS NULL
                     OR ifs.last_attempted_at <
                        now() - make_interval(
                          hours => COALESCE(ifs.cadence_hours,
                                            {_DEFAULT_IMAGERY_CADENCE_HOURS}))))
              AS overdue_count
        FROM imagery_farm_subscriptions ifs
        WHERE ifs.deleted_at IS NULL
        GROUP BY ifs.farm_id
    ),
    ifj_agg AS (
        SELECT
            fj.farm_id,
            max(fj.requested_at) AS last_sync_at,
            count(*) FILTER
              (WHERE fj.status = 'failed'
                AND fj.requested_at > now() - interval '24 hours')
              AS failed_24h,
            count(*) FILTER
              (WHERE fj.status IN ('pending', 'requested', 'running'))
              AS running_count
        FROM imagery_farm_ingestion_jobs fj
        GROUP BY fj.farm_id
    )
    SELECT
        f.id   AS farm_id,
        f.name AS farm_name,
        (COALESCE(block_roll.weather_active_subs, 0)
         + COALESCE(wfs_agg.active_subs, 0))::bigint      AS weather_active_subs,
        -- GREATEST ignores NULLs and returns NULL only when every argument
        -- is NULL, which is exactly "neither path has ever synced".
        GREATEST(block_roll.weather_last_sync_at,
                 wfs_agg.last_sync_at)                    AS weather_last_sync_at,
        GREATEST(block_roll.weather_last_failed_at,
                 wfs_agg.last_failed_at)                  AS weather_last_failed_at,
        (COALESCE(block_roll.imagery_active_subs, 0)
         + COALESCE(ifs_agg.active_subs, 0))::bigint      AS imagery_active_subs,
        GREATEST(block_roll.imagery_last_sync_at,
                 ifj_agg.last_sync_at)                    AS imagery_last_sync_at,
        (COALESCE(block_roll.imagery_failed_24h, 0)
         + COALESCE(ifj_agg.failed_24h, 0))::bigint       AS imagery_failed_24h,
        (COALESCE(block_roll.weather_failed_24h, 0)
         + COALESCE(wfa_agg.failed_24h, 0))::bigint       AS weather_failed_24h,
        (COALESCE(block_roll.weather_running_count, 0)
         + COALESCE(wfa_agg.running_count, 0))::bigint    AS weather_running_count,
        (COALESCE(block_roll.imagery_running_count, 0)
         + COALESCE(ifj_agg.running_count, 0))::bigint    AS imagery_running_count,
        (COALESCE(block_roll.weather_overdue_count, 0)
         + COALESCE(wfs_agg.overdue_count, 0))::bigint    AS weather_overdue_count,
        (COALESCE(block_roll.imagery_overdue_count, 0)
         + COALESCE(ifs_agg.overdue_count, 0))::bigint    AS imagery_overdue_count
    FROM farms f
    LEFT JOIN block_roll ON block_roll.farm_id = f.id
    LEFT JOIN wfs_agg    ON wfs_agg.farm_id    = f.id
    LEFT JOIN wfa_agg    ON wfa_agg.farm_id    = f.id
    LEFT JOIN ifs_agg    ON ifs_agg.farm_id    = f.id
    LEFT JOIN ifj_agg    ON ifj_agg.farm_id    = f.id
    WHERE f.deleted_at IS NULL
"""

# Verbatim from 0056, so the downgrade restores exactly what was there.
_FARM_VIEW_BLOCK_ONLY = """
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
# v_integration_recent_attempts — three arms, and a named scope
# ---------------------------------------------------------------------------

# Shared streak plumbing. `failed_streak_position` partitions by
# subscription_id, and a farm subscription id never collides with a block
# one, so the farm arm gets its own streaks for free.
_ATTEMPTS_VIEW_BOTH_PATHS = """
    CREATE VIEW v_integration_recent_attempts AS
    WITH weather_streak AS (
        SELECT
            wa.id,
            wa.subscription_id,
            wa.block_id,
            wa.farm_id,
            wa.provider_code,
            wa.started_at,
            wa.completed_at,
            wa.status,
            wa.duration_ms,
            wa.rows_ingested,
            wa.error_code,
            wa.error_message,
            SUM(CASE WHEN wa.status = 'succeeded' THEN 1 ELSE 0 END)
              OVER (
                PARTITION BY wa.subscription_id
                ORDER BY wa.started_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ) AS streak_id
        FROM weather_ingestion_attempts wa
    ),
    weather_final AS (
        SELECT
            *,
            CASE
                WHEN status = 'failed' THEN
                    ROW_NUMBER() OVER (
                        PARTITION BY subscription_id, streak_id
                        ORDER BY started_at
                    )
                ELSE 0
            END AS failed_streak_position
        FROM weather_streak
    ),
    imagery_streak AS (
        SELECT
            ij.id,
            ij.subscription_id,
            ij.block_id,
            ij.product_id,
            ij.scene_id,
            ij.requested_at,
            ij.started_at,
            ij.completed_at,
            ij.status,
            ij.error_code,
            ij.error_message,
            SUM(CASE WHEN ij.status = 'succeeded' THEN 1 ELSE 0 END)
              OVER (
                PARTITION BY ij.subscription_id
                ORDER BY ij.requested_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ) AS streak_id
        FROM imagery_ingestion_jobs ij
    ),
    imagery_final AS (
        SELECT
            *,
            CASE
                WHEN status = 'failed' THEN
                    ROW_NUMBER() OVER (
                        PARTITION BY subscription_id, streak_id
                        ORDER BY requested_at
                    )
                ELSE 0
            END AS failed_streak_position
        FROM imagery_streak
    ),
    farm_imagery_streak AS (
        SELECT
            fj.id,
            fj.subscription_id,
            fj.farm_id,
            fj.product_id,
            fj.scene_id,
            fj.requested_at,
            fj.started_at,
            fj.completed_at,
            fj.status,
            fj.error_code,
            fj.error_message,
            SUM(CASE WHEN fj.status = 'succeeded' THEN 1 ELSE 0 END)
              OVER (
                PARTITION BY fj.subscription_id
                ORDER BY fj.requested_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ) AS streak_id
        FROM imagery_farm_ingestion_jobs fj
    ),
    farm_imagery_final AS (
        SELECT
            *,
            CASE
                WHEN status = 'failed' THEN
                    ROW_NUMBER() OVER (
                        PARTITION BY subscription_id, streak_id
                        ORDER BY requested_at
                    )
                ELSE 0
            END AS failed_streak_position
        FROM farm_imagery_streak
    )
    SELECT
        wf.id                 AS attempt_id,
        'weather'::text       AS kind,
        -- 0077 made a weather attempt farm-scoped by leaving block_id NULL.
        CASE WHEN wf.block_id IS NULL THEN 'farm' ELSE 'block' END AS scope,
        wf.subscription_id    AS subscription_id,
        wf.block_id           AS block_id,
        wf.farm_id            AS farm_id,
        wf.provider_code      AS provider_code,
        wf.started_at         AS started_at,
        wf.started_at         AS queued_at,
        wf.completed_at       AS completed_at,
        wf.status             AS status,
        wf.duration_ms        AS duration_ms,
        0                     AS wait_ms,
        wf.duration_ms        AS run_ms,
        wf.rows_ingested      AS rows_ingested,
        wf.error_code         AS error_code,
        wf.error_message      AS error_message,
        NULL::text            AS scene_id,
        wf.failed_streak_position AS failed_streak_position
    FROM weather_final wf
    WHERE wf.started_at > now() - interval '14 days'

    UNION ALL

    SELECT
        ifin.id               AS attempt_id,
        'imagery'::text       AS kind,
        'block'::text         AS scope,
        ifin.subscription_id  AS subscription_id,
        ifin.block_id         AS block_id,
        (SELECT b.farm_id FROM blocks b WHERE b.id = ifin.block_id) AS farm_id,
        (SELECT ip.code
           FROM public.imagery_products ip
           WHERE ip.id = ifin.product_id) AS provider_code,
        COALESCE(ifin.started_at, ifin.requested_at) AS started_at,
        ifin.requested_at     AS queued_at,
        ifin.completed_at     AS completed_at,
        CASE
          WHEN ifin.status IN ('pending', 'requested') THEN 'running'
          ELSE ifin.status
        END                   AS status,
        CASE
          WHEN ifin.completed_at IS NULL OR ifin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ifin.completed_at - ifin.started_at)) * 1000)::int)
        END                   AS duration_ms,
        CASE
          WHEN ifin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ifin.started_at - ifin.requested_at)) * 1000)::int)
        END                   AS wait_ms,
        CASE
          WHEN ifin.completed_at IS NULL OR ifin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ifin.completed_at - ifin.started_at)) * 1000)::int)
        END                   AS run_ms,
        NULL::int             AS rows_ingested,
        ifin.error_code       AS error_code,
        ifin.error_message    AS error_message,
        ifin.scene_id         AS scene_id,
        ifin.failed_streak_position AS failed_streak_position
    FROM imagery_final ifin
    WHERE ifin.requested_at > now() - interval '14 days'

    UNION ALL

    -- The farm acquisition path. One job covers every block of the farm,
    -- so there is no block to name and `block_id` is legitimately NULL —
    -- `scope` is what a reader should key on, not the null.
    SELECT
        ffin.id               AS attempt_id,
        'imagery'::text       AS kind,
        'farm'::text          AS scope,
        ffin.subscription_id  AS subscription_id,
        NULL::uuid            AS block_id,
        ffin.farm_id          AS farm_id,
        (SELECT ip.code
           FROM public.imagery_products ip
           WHERE ip.id = ffin.product_id) AS provider_code,
        COALESCE(ffin.started_at, ffin.requested_at) AS started_at,
        ffin.requested_at     AS queued_at,
        ffin.completed_at     AS completed_at,
        -- A farm job skips as plain 'skipped' where a block job says
        -- 'skipped_cloud'/'skipped_duplicate'; both are folded to the
        -- vocabulary this view already publishes.
        CASE
          WHEN ffin.status IN ('pending', 'requested') THEN 'running'
          WHEN ffin.status IN ('skipped_cloud', 'skipped_duplicate') THEN 'skipped'
          ELSE ffin.status
        END                   AS status,
        CASE
          WHEN ffin.completed_at IS NULL OR ffin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ffin.completed_at - ffin.started_at)) * 1000)::int)
        END                   AS duration_ms,
        CASE
          WHEN ffin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ffin.started_at - ffin.requested_at)) * 1000)::int)
        END                   AS wait_ms,
        CASE
          WHEN ffin.completed_at IS NULL OR ffin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ffin.completed_at - ffin.started_at)) * 1000)::int)
        END                   AS run_ms,
        NULL::int             AS rows_ingested,
        ffin.error_code       AS error_code,
        ffin.error_message    AS error_message,
        ffin.scene_id         AS scene_id,
        ffin.failed_streak_position AS failed_streak_position
    FROM farm_imagery_final ffin
    WHERE ffin.requested_at > now() - interval '14 days'
"""

# Verbatim from 0024 upgrade(), for the downgrade.
_ATTEMPTS_VIEW_BLOCK_ONLY = """
    CREATE VIEW v_integration_recent_attempts AS
    WITH weather_streak AS (
        SELECT
            wa.id,
            wa.subscription_id,
            wa.block_id,
            wa.farm_id,
            wa.provider_code,
            wa.started_at,
            wa.completed_at,
            wa.status,
            wa.duration_ms,
            wa.rows_ingested,
            wa.error_code,
            wa.error_message,
            SUM(CASE WHEN wa.status = 'succeeded' THEN 1 ELSE 0 END)
              OVER (
                PARTITION BY wa.subscription_id
                ORDER BY wa.started_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ) AS streak_id
        FROM weather_ingestion_attempts wa
    ),
    weather_final AS (
        SELECT
            *,
            CASE
                WHEN status = 'failed' THEN
                    ROW_NUMBER() OVER (
                        PARTITION BY subscription_id, streak_id
                        ORDER BY started_at
                    )
                ELSE 0
            END AS failed_streak_position
        FROM weather_streak
    ),
    imagery_streak AS (
        SELECT
            ij.id,
            ij.subscription_id,
            ij.block_id,
            ij.product_id,
            ij.scene_id,
            ij.requested_at,
            ij.started_at,
            ij.completed_at,
            ij.status,
            ij.error_code,
            ij.error_message,
            SUM(CASE WHEN ij.status = 'succeeded' THEN 1 ELSE 0 END)
              OVER (
                PARTITION BY ij.subscription_id
                ORDER BY ij.requested_at
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ) AS streak_id
        FROM imagery_ingestion_jobs ij
    ),
    imagery_final AS (
        SELECT
            *,
            CASE
                WHEN status = 'failed' THEN
                    ROW_NUMBER() OVER (
                        PARTITION BY subscription_id, streak_id
                        ORDER BY requested_at
                    )
                ELSE 0
            END AS failed_streak_position
        FROM imagery_streak
    )
    SELECT
        wf.id                 AS attempt_id,
        'weather'::text       AS kind,
        wf.subscription_id    AS subscription_id,
        wf.block_id           AS block_id,
        wf.farm_id            AS farm_id,
        wf.provider_code      AS provider_code,
        wf.started_at         AS started_at,
        wf.started_at         AS queued_at,
        wf.completed_at       AS completed_at,
        wf.status             AS status,
        wf.duration_ms        AS duration_ms,
        0                     AS wait_ms,
        wf.duration_ms        AS run_ms,
        wf.rows_ingested      AS rows_ingested,
        wf.error_code         AS error_code,
        wf.error_message      AS error_message,
        NULL::text            AS scene_id,
        wf.failed_streak_position AS failed_streak_position
    FROM weather_final wf
    WHERE wf.started_at > now() - interval '14 days'

    UNION ALL

    SELECT
        ifin.id               AS attempt_id,
        'imagery'::text       AS kind,
        ifin.subscription_id  AS subscription_id,
        ifin.block_id         AS block_id,
        (SELECT b.farm_id FROM blocks b WHERE b.id = ifin.block_id) AS farm_id,
        (SELECT ip.code
           FROM public.imagery_products ip
           WHERE ip.id = ifin.product_id) AS provider_code,
        COALESCE(ifin.started_at, ifin.requested_at) AS started_at,
        ifin.requested_at     AS queued_at,
        ifin.completed_at     AS completed_at,
        CASE
          WHEN ifin.status IN ('pending', 'requested') THEN 'running'
          ELSE ifin.status
        END                   AS status,
        CASE
          WHEN ifin.completed_at IS NULL OR ifin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ifin.completed_at - ifin.started_at)) * 1000)::int)
        END                   AS duration_ms,
        CASE
          WHEN ifin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ifin.started_at - ifin.requested_at)) * 1000)::int)
        END                   AS wait_ms,
        CASE
          WHEN ifin.completed_at IS NULL OR ifin.started_at IS NULL THEN NULL
          ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                   (ifin.completed_at - ifin.started_at)) * 1000)::int)
        END                   AS run_ms,
        NULL::int             AS rows_ingested,
        ifin.error_code       AS error_code,
        ifin.error_message    AS error_message,
        ifin.scene_id         AS scene_id,
        ifin.failed_streak_position AS failed_streak_position
    FROM imagery_final ifin
    WHERE ifin.requested_at > now() - interval '14 days'
"""


def upgrade() -> None:
    # The farm view depends on the block view, so it goes first in both
    # directions. The block view itself is untouched.
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute(_FARM_VIEW_BOTH_PATHS)

    op.execute("DROP VIEW IF EXISTS v_integration_recent_attempts")
    op.execute(_ATTEMPTS_VIEW_BOTH_PATHS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_integration_recent_attempts")
    op.execute(_ATTEMPTS_VIEW_BLOCK_ONLY)

    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute(_FARM_VIEW_BLOCK_ONLY)
