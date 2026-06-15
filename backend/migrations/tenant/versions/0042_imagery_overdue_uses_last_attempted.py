"""Re-point imagery `overdue` health check from ingest-time to poll-time.

`v_{farm,block}_integration_health.imagery_overdue_count` previously
flagged a subscription overdue when `last_successful_ingest_at` fell
behind `cadence_hours`. That conflated two different clocks:

  - the *poll* cadence (every 24h — the part we control), and
  - the satellite *revisit* cadence (~5 days for a single-orbit AOI,
    longer under cloud — entirely outside our control).

The pre-fix discovery task masked the mismatch by bumping
`last_successful_ingest_at` on every poll (even empty ones), so overdue
never fired. The companion task fix stops that lie: the ingest watermark
now advances only on a real ingest. To keep "overdue" meaning "the
poller is not polling on cadence" (a genuine integration fault) rather
than "no new scene this revisit gap" (normal sky), the imagery predicate
now keys off `last_attempted_at` — the wall-clock heartbeat.

Weather is unchanged: it delivers data every cadence, so
`last_successful_ingest_at` remains the correct staleness signal there.

Only the `imagery_overdue_count` predicate changes; every other column
is reproduced verbatim from migration 0022.

Revision ID: 0042
Revises: 0041
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror app.core.settings defaults; see migration 0022 for why hard-coding
# in the view is acceptable (snapshot of state, not behavioural policy).
_DEFAULT_WEATHER_CADENCE_HOURS = 3
_DEFAULT_IMAGERY_CADENCE_HOURS = 24


def _farm_view(*, imagery_overdue_column: str) -> str:
    return f"""
        CREATE OR REPLACE VIEW v_farm_integration_health AS
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
                AND (ias.{imagery_overdue_column} IS NULL
                     OR ias.{imagery_overdue_column} <
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


def _block_view(*, imagery_overdue_column: str) -> str:
    return f"""
        CREATE OR REPLACE VIEW v_block_integration_health AS
        SELECT
            b.id        AS block_id,
            b.farm_id   AS farm_id,
            b.name      AS block_name,
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
                AND (ias.{imagery_overdue_column} IS NULL
                     OR ias.{imagery_overdue_column} <
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


def upgrade() -> None:
    # CREATE OR REPLACE keeps the column list identical (only the WHERE
    # predicate of an existing aggregate changes), so no DROP is needed.
    op.execute(_farm_view(imagery_overdue_column="last_attempted_at"))
    op.execute(_block_view(imagery_overdue_column="last_attempted_at"))


def downgrade() -> None:
    op.execute(_farm_view(imagery_overdue_column="last_successful_ingest_at"))
    op.execute(_block_view(imagery_overdue_column="last_successful_ingest_at"))
