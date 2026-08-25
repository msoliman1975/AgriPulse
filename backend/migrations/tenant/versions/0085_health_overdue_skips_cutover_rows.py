"""Overdue must not count the subscriptions the sweeps deliberately skip.

Since 0074/0077 a farm can acquire on its own behalf, and both sweeps stop
polling the block rows once it does:

* `WeatherRepository.list_due_farm_provider_pairs` drops a block weather row
  whose farm has an active farm row for the same provider.
* `ImageryRepository.list_active_subscriptions_due` drops a block imagery row
  whose farm fetches that product as one AOI (`fetch_farm_aoi`).

Nothing then advances those rows' watermarks, so `v_farm_integration_health`
counts every one of them as overdue for the rest of time. 0078 fixed the
timestamps this way — `GREATEST` over both paths — but left the counts as a
plain sum of the block rollup and the farm rollup.

Measured on prod (`tenant_019eafdc242c7320948e13490efc67dd`, 2026-08-25):

  Bashier Elkhier   weather synced 04:33 today, imagery through two
                    farm-AOI subscriptions
    -> the page said "36 overdue" weather and "36 overdue" imagery, one per
       block, on a farm where both streams were working.

  B-Elkair-Suez     weather synced 06:01 today
    -> "36 overdue" weather, same cause.

The Queue tab already had the weather half of this right
(`integrations_health.service.list_queue`), so the same page showed two
different answers depending on which tab was open.

This restates `v_farm_integration_health` with both overdue counts read from
the subscription tables under the sweeps' own predicates. Nothing else in the
view changes, and `v_block_integration_health` stays untouched: a block view
has no farm-level row to compare against, and 0078's reason for leaving it
alone still holds.

Revision ID: 0085
Revises: 0084
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror app.core.settings defaults; see migration 0022 for why hard-coding
# these in the view body is acceptable (a snapshot of state, not policy).
_DEFAULT_WEATHER_CADENCE_HOURS = 3
_DEFAULT_IMAGERY_CADENCE_HOURS = 24


_FARM_VIEW_SWEEP_AWARE_OVERDUE = f"""
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
    ),
    -- Block rows the sweep has stopped polling must not be counted as
    -- overdue. `list_due_farm_provider_pairs` skips a block weather row once
    -- its farm has an active farm row for the same provider, and
    -- `list_active_subscriptions_due` skips a block imagery row once its
    -- farm fetches that product as one AOI. Their watermarks then freeze at
    -- the cut-over and every one of them reads overdue for ever. Prod,
    -- 2026-08-25: agrosina showed "36 overdue" weather on both farms whose
    -- weather had synced within the hour, and "36 overdue" imagery on the
    -- farm whose blocks are covered by two farm-AOI subscriptions. Both
    -- predicates below are copied from the sweeps they mirror.
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


# Verbatim from 0078, so the downgrade restores exactly what was there.
_FARM_VIEW_0078 = f"""
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


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute(_FARM_VIEW_SWEEP_AWARE_OVERDUE)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute(_FARM_VIEW_0078)
