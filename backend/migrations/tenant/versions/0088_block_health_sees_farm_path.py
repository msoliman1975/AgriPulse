"""The per-block health view must see the farm acquisition path.

0078 taught `v_farm_integration_health` about `weather_farm_subscriptions`,
`imagery_farm_subscriptions` and `imagery_farm_ingestion_jobs`, and left
`v_block_integration_health` reading only the two block-keyed subscription
tables. The Blocks tab is therefore wrong in both directions, and both were
measured on prod on 2026-08-28:

  Valley Farms / Mango Republic
    36 blocks, 0 block subscriptions of any kind.
    1 farm weather subscription, synced 07:07 that morning.
    2 farm imagery subscriptions, last attempt 20:20 the evening before.
    -> every block reads "Idle - No active subscription", on both columns.

  agrosina / Bashier Elkhier
    36 block weather rows frozen at 2026-08-13 17:38, because
    `list_due_farm_provider_pairs` stopped polling them at the cut-over.
    36 block imagery rows frozen at 2026-08-10 08:41, same reason.
    The farm synced weather at 06:52 and attempted imagery at 20:20.
    -> every block reads "Failing", on both columns.

  agrosina / B-Elkair-Suez
    Same frozen weather rows; 36 blocks read "Failing" on a farm whose
    weather synced at 01:52 that night.

So 108 block rows on prod stated the opposite of the truth.

The rule this migration applies is the sweeps' own rule. A block weather row
is skipped once its farm has an active farm row for the same provider. A
block imagery row is skipped once its farm fetches that product as one AOI.
Skipped rows stop being polled, so they carry no information at all and are
dropped from every subscription-derived column. What serves the block
instead is the farm row, so the farm row is what the block reports.

Three views, so the two public ones cannot drift apart:

* `v_block_own_integration_health` - new, internal. The block-keyed half,
  with the sweeps' skip rule applied to the subscription-derived columns.
  Same columns as the old block view.

* `v_block_integration_health` - the own half plus the farm rows that cover
  the block. Same columns as before, so the API contract does not move.

* `v_farm_integration_health` - 0085's definition with one name changed:
  its `block_roll` now reads the own view. Without that the farm numbers
  would count the farm subscription twice.

Dropping the skipped rows also fixes the count 0085 left behind. Bashier
Elkhier reported 37 active weather subscriptions: 36 frozen block rows plus
the 1 row that fetches. It now reports 1. Its imagery count moves from 38 to
2 the same way.

Attempt-derived and job-derived columns keep their old block-keyed
definitions. A skipped block stops producing attempts and jobs, so its
history ages out of the 24-hour windows on its own.

Revision ID: 0088
Revises: 0087
Create Date: 2026-08-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror app.core.settings defaults; see migration 0022 for why hard-coding
# these in the view body is acceptable (a snapshot of state, not policy).
_DEFAULT_WEATHER_CADENCE_HOURS = 3
_DEFAULT_IMAGERY_CADENCE_HOURS = 24

_NEG_INF = "'-infinity'::timestamptz"


# ---------------------------------------------------------------------------
# The block-keyed half, with the sweeps' skip rule applied.
# ---------------------------------------------------------------------------

_BLOCK_OWN_VIEW = f"""
    CREATE VIEW v_block_own_integration_health AS
    WITH ws_agg AS (
        SELECT
            ws.block_id,
            count(*) FILTER (WHERE ws.is_active) AS weather_active_subs,
            max(ws.last_successful_ingest_at) AS weather_last_sync_at,
            max(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, {_NEG_INF}))
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
        JOIN blocks b ON b.id = ws.block_id
        -- Copied from `WeatherRepository.list_due_farm_provider_pairs`. A row
        -- the sweep skips has a frozen watermark, so every column derived
        -- from it is a statement about the past, not about this block.
        WHERE NOT EXISTS (
            SELECT 1 FROM weather_farm_subscriptions wfs
             WHERE wfs.farm_id = b.farm_id
               AND wfs.provider_code = ws.provider_code
               AND wfs.is_active
               AND wfs.deleted_at IS NULL
        )
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
        JOIN blocks b ON b.id = ias.block_id
        -- Copied from `ImageryRepository.list_active_subscriptions_due`.
        WHERE NOT EXISTS (
            SELECT 1 FROM imagery_farm_subscriptions ifs
             WHERE ifs.farm_id = b.farm_id
               AND ifs.product_id = ias.product_id
               AND ifs.is_active
               AND ifs.fetch_farm_aoi
               AND ifs.deleted_at IS NULL
        )
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


# ---------------------------------------------------------------------------
# The farm-keyed half. One text, used by both public views, so a change to
# the rule reaches the Farms tab and the Blocks tab together.
# ---------------------------------------------------------------------------

_FARM_PATH_CTES = f"""
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
                     COALESCE(wfs.last_successful_ingest_at, {_NEG_INF}))
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
    -- block half of these same counts comes from the own view, so filtering
    -- here is what keeps the two from double-counting.
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
"""


_BLOCK_VIEW_WITH_FARM_PATH = f"""
    CREATE VIEW v_block_integration_health AS
    WITH
{_FARM_PATH_CTES}
    SELECT
        h.block_id,
        h.farm_id,
        h.block_name,
        (h.weather_active_subs
         + COALESCE(wfs_agg.active_subs, 0))::bigint      AS weather_active_subs,
        -- GREATEST ignores NULLs and returns NULL only when every argument
        -- is NULL, which is exactly "neither path has ever synced".
        GREATEST(h.weather_last_sync_at,
                 wfs_agg.last_sync_at)                    AS weather_last_sync_at,
        GREATEST(h.weather_last_failed_at,
                 wfs_agg.last_failed_at)                  AS weather_last_failed_at,
        (h.imagery_active_subs
         + COALESCE(ifs_agg.active_subs, 0))::bigint      AS imagery_active_subs,
        GREATEST(h.imagery_last_sync_at,
                 ifj_agg.last_sync_at)                    AS imagery_last_sync_at,
        (h.imagery_failed_24h
         + COALESCE(ifj_agg.failed_24h, 0))::bigint       AS imagery_failed_24h,
        (h.weather_failed_24h
         + COALESCE(wfa_agg.failed_24h, 0))::bigint       AS weather_failed_24h,
        (h.weather_running_count
         + COALESCE(wfa_agg.running_count, 0))::bigint    AS weather_running_count,
        (h.imagery_running_count
         + COALESCE(ifj_agg.running_count, 0))::bigint    AS imagery_running_count,
        (h.weather_overdue_count
         + COALESCE(wfs_agg.overdue_count, 0))::bigint    AS weather_overdue_count,
        (h.imagery_overdue_count
         + COALESCE(ifs_agg.overdue_count, 0))::bigint    AS imagery_overdue_count
    FROM v_block_own_integration_health h
    LEFT JOIN wfs_agg ON wfs_agg.farm_id = h.farm_id
    LEFT JOIN wfa_agg ON wfa_agg.farm_id = h.farm_id
    LEFT JOIN ifs_agg ON ifs_agg.farm_id = h.farm_id
    LEFT JOIN ifj_agg ON ifj_agg.farm_id = h.farm_id
"""


_FARM_VIEW_ON_OWN_VIEW = f"""
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
            sum(h.imagery_running_count) AS imagery_running_count
        FROM v_block_own_integration_health h
        GROUP BY h.farm_id
    ),
{_FARM_PATH_CTES},
    -- The own view already drops the rows the sweeps skip, so a plain sum of
    -- its overdue column would now be correct. These two CTEs stay because
    -- they also apply the `is_active` and `deleted_at` filters, which keeps
    -- every farm number identical to 0085's.
    wbs_agg AS (
        SELECT
            b.farm_id,
            count(*) FILTER
              (WHERE ws.last_successful_ingest_at IS NULL
                  OR ws.last_successful_ingest_at <
                     now() - make_interval(
                       hours => COALESCE(ws.cadence_hours,
                                         {_DEFAULT_WEATHER_CADENCE_HOURS})))
              AS overdue_count
        FROM weather_subscriptions ws
        JOIN blocks b ON b.id = ws.block_id AND b.deleted_at IS NULL
        WHERE ws.is_active
          AND ws.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM weather_farm_subscriptions wfs
               WHERE wfs.farm_id = b.farm_id
                 AND wfs.provider_code = ws.provider_code
                 AND wfs.is_active
                 AND wfs.deleted_at IS NULL
          )
        GROUP BY b.farm_id
    ),
    ibs_agg AS (
        SELECT
            b.farm_id,
            count(*) FILTER
              (WHERE ias.last_attempted_at IS NULL
                  OR ias.last_attempted_at <
                     now() - make_interval(
                       hours => COALESCE(ias.cadence_hours,
                                         {_DEFAULT_IMAGERY_CADENCE_HOURS})))
              AS overdue_count
        FROM imagery_aoi_subscriptions ias
        JOIN blocks b ON b.id = ias.block_id AND b.deleted_at IS NULL
        WHERE ias.is_active
          AND ias.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM imagery_farm_subscriptions ifs
               WHERE ifs.farm_id = b.farm_id
                 AND ifs.product_id = ias.product_id
                 AND ifs.is_active
                 AND ifs.fetch_farm_aoi
                 AND ifs.deleted_at IS NULL
          )
        GROUP BY b.farm_id
    )
    SELECT
        f.id   AS farm_id,
        f.name AS farm_name,
        (COALESCE(block_roll.weather_active_subs, 0)
         + COALESCE(wfs_agg.active_subs, 0))::bigint      AS weather_active_subs,
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
        (COALESCE(wbs_agg.overdue_count, 0)
         + COALESCE(wfs_agg.overdue_count, 0))::bigint    AS weather_overdue_count,
        (COALESCE(ibs_agg.overdue_count, 0)
         + COALESCE(ifs_agg.overdue_count, 0))::bigint    AS imagery_overdue_count
    FROM farms f
    LEFT JOIN block_roll ON block_roll.farm_id = f.id
    LEFT JOIN wfs_agg    ON wfs_agg.farm_id    = f.id
    LEFT JOIN wfa_agg    ON wfa_agg.farm_id    = f.id
    LEFT JOIN ifs_agg    ON ifs_agg.farm_id    = f.id
    LEFT JOIN ifj_agg    ON ifj_agg.farm_id    = f.id
    LEFT JOIN wbs_agg    ON wbs_agg.farm_id    = f.id
    LEFT JOIN ibs_agg    ON ibs_agg.farm_id    = f.id
    WHERE f.deleted_at IS NULL
"""


# ---------------------------------------------------------------------------
# Previous definitions, reproduced so the downgrade restores exactly what
# was there. The block view is 0056's; the farm view is 0085's.
# ---------------------------------------------------------------------------

_BLOCK_VIEW_0056 = f"""
    CREATE VIEW v_block_integration_health AS
    WITH ws_agg AS (
        SELECT
            ws.block_id,
            count(*) FILTER (WHERE ws.is_active) AS weather_active_subs,
            max(ws.last_successful_ingest_at) AS weather_last_sync_at,
            max(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, {_NEG_INF}))
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


_FARM_VIEW_0085 = f"""
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
{_FARM_PATH_CTES},
    wbs_agg AS (
        SELECT
            b.farm_id,
            count(*) FILTER
              (WHERE ws.last_successful_ingest_at IS NULL
                  OR ws.last_successful_ingest_at <
                     now() - make_interval(
                       hours => COALESCE(ws.cadence_hours,
                                         {_DEFAULT_WEATHER_CADENCE_HOURS})))
              AS overdue_count
        FROM weather_subscriptions ws
        JOIN blocks b ON b.id = ws.block_id AND b.deleted_at IS NULL
        WHERE ws.is_active
          AND ws.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM weather_farm_subscriptions wfs
               WHERE wfs.farm_id = b.farm_id
                 AND wfs.provider_code = ws.provider_code
                 AND wfs.is_active
                 AND wfs.deleted_at IS NULL
          )
        GROUP BY b.farm_id
    ),
    ibs_agg AS (
        SELECT
            b.farm_id,
            count(*) FILTER
              (WHERE ias.last_attempted_at IS NULL
                  OR ias.last_attempted_at <
                     now() - make_interval(
                       hours => COALESCE(ias.cadence_hours,
                                         {_DEFAULT_IMAGERY_CADENCE_HOURS})))
              AS overdue_count
        FROM imagery_aoi_subscriptions ias
        JOIN blocks b ON b.id = ias.block_id AND b.deleted_at IS NULL
        WHERE ias.is_active
          AND ias.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM imagery_farm_subscriptions ifs
               WHERE ifs.farm_id = b.farm_id
                 AND ifs.product_id = ias.product_id
                 AND ifs.is_active
                 AND ifs.fetch_farm_aoi
                 AND ifs.deleted_at IS NULL
          )
        GROUP BY b.farm_id
    )
    SELECT
        f.id   AS farm_id,
        f.name AS farm_name,
        (COALESCE(block_roll.weather_active_subs, 0)
         + COALESCE(wfs_agg.active_subs, 0))::bigint      AS weather_active_subs,
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
        (COALESCE(wbs_agg.overdue_count, 0)
         + COALESCE(wfs_agg.overdue_count, 0))::bigint    AS weather_overdue_count,
        (COALESCE(ibs_agg.overdue_count, 0)
         + COALESCE(ifs_agg.overdue_count, 0))::bigint    AS imagery_overdue_count
    FROM farms f
    LEFT JOIN block_roll ON block_roll.farm_id = f.id
    LEFT JOIN wfs_agg    ON wfs_agg.farm_id    = f.id
    LEFT JOIN wfa_agg    ON wfa_agg.farm_id    = f.id
    LEFT JOIN ifs_agg    ON ifs_agg.farm_id    = f.id
    LEFT JOIN ifj_agg    ON ifj_agg.farm_id    = f.id
    LEFT JOIN wbs_agg    ON wbs_agg.farm_id    = f.id
    LEFT JOIN ibs_agg    ON ibs_agg.farm_id    = f.id
    WHERE f.deleted_at IS NULL
"""


def upgrade() -> None:
    # Drop in dependency order: the farm view reads the block view today.
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute("DROP VIEW IF EXISTS v_block_integration_health")
    op.execute(_BLOCK_OWN_VIEW)
    op.execute(_BLOCK_VIEW_WITH_FARM_PATH)
    op.execute(_FARM_VIEW_ON_OWN_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute("DROP VIEW IF EXISTS v_block_integration_health")
    op.execute("DROP VIEW IF EXISTS v_block_own_integration_health")
    op.execute(_BLOCK_VIEW_0056)
    op.execute(_FARM_VIEW_0085)
