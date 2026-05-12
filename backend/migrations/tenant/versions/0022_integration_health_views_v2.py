"""Extend integration-health views and add recent-attempts view.

Builds on migration 0019 (`v_farm_integration_health`,
`v_block_integration_health`) and 0021 (`weather_ingestion_attempts`).

Adds five columns to both views:
  - weather_failed_24h  — count of failed attempts in last 24h
  - weather_running_count — currently 'running' attempts
  - imagery_running_count — imagery jobs with status in (requested, running)
  - weather_overdue_count — active subs past their cadence
  - imagery_overdue_count — same for imagery AOI subs

Adds a new view:
  - v_integration_recent_attempts — union of weather + imagery attempts
    in one row shape; consumers apply their own ORDER BY + LIMIT.

`CREATE OR REPLACE VIEW` requires the column list to be a strict
superset of the existing definition, so we recreate the columns in the
same order as 0019 first, then append the new ones.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Default weather cadence — duplicates `app.core.settings.weather_default_cadence_hours`.
# Hard-coding here is acceptable because the view is a snapshot of pipeline
# state, not a behavioral policy; the writer-side cadence is what governs
# actual fetches. If we ever make this tenant-configurable, the view will
# need to join against the resolved setting per subscription.
_DEFAULT_WEATHER_CADENCE_HOURS = 3
_DEFAULT_IMAGERY_CADENCE_HOURS = 24


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE VIEW v_farm_integration_health AS
        SELECT
            f.id   AS farm_id,
            f.name AS farm_name,
            -- weather (existing)
            COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
              AS weather_active_subs,
            MAX(ws.last_successful_ingest_at)
              AS weather_last_sync_at,
            MAX(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            -- imagery (existing)
            COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
              AS imagery_active_subs,
            MAX(ij.requested_at)
              AS imagery_last_sync_at,
            COUNT(DISTINCT ij.id) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h,
            -- new (PR-IH2)
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
                AND (ias.last_successful_ingest_at IS NULL
                     OR ias.last_successful_ingest_at <
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
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW v_block_integration_health AS
        SELECT
            b.id        AS block_id,
            b.farm_id   AS farm_id,
            b.name      AS block_name,
            -- weather (existing)
            COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
              AS weather_active_subs,
            MAX(ws.last_successful_ingest_at)
              AS weather_last_sync_at,
            MAX(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            -- imagery (existing)
            COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
              AS imagery_active_subs,
            MAX(ij.requested_at)
              AS imagery_last_sync_at,
            COUNT(DISTINCT ij.id) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h,
            -- new (PR-IH2)
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
                AND (ias.last_successful_ingest_at IS NULL
                     OR ias.last_successful_ingest_at <
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
    )

    # Union view — same shape for weather + imagery so the Runs tab UI is
    # a single table. Bounded to the last 14 days at the view level so a
    # naïve `SELECT * LIMIT N` from the API doesn't scan history forever.
    op.execute(
        """
        CREATE OR REPLACE VIEW v_integration_recent_attempts AS
        SELECT
            wa.id              AS attempt_id,
            'weather'::text    AS kind,
            wa.subscription_id AS subscription_id,
            wa.block_id        AS block_id,
            wa.farm_id         AS farm_id,
            wa.provider_code   AS provider_code,
            wa.started_at      AS started_at,
            wa.completed_at    AS completed_at,
            wa.status          AS status,
            wa.duration_ms     AS duration_ms,
            wa.rows_ingested   AS rows_ingested,
            wa.error_code      AS error_code,
            wa.error_message   AS error_message,
            NULL::text         AS scene_id
        FROM weather_ingestion_attempts wa
        WHERE wa.started_at > now() - interval '14 days'
        UNION ALL
        SELECT
            ij.id              AS attempt_id,
            'imagery'::text    AS kind,
            ij.subscription_id AS subscription_id,
            ij.block_id        AS block_id,
            (SELECT b.farm_id FROM blocks b WHERE b.id = ij.block_id) AS farm_id,
            (SELECT ip.code
               FROM public.imagery_products ip
               WHERE ip.id = ij.product_id)
                               AS provider_code,
            ij.requested_at    AS started_at,
            ij.completed_at    AS completed_at,
            CASE
              WHEN ij.status IN ('pending', 'requested') THEN 'running'
              ELSE ij.status
            END                AS status,
            CASE
              WHEN ij.completed_at IS NULL OR ij.started_at IS NULL THEN NULL
              ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                       (ij.completed_at - ij.started_at)) * 1000)::int)
            END                AS duration_ms,
            NULL::int          AS rows_ingested,
            NULL::text         AS error_code,
            ij.error_message   AS error_message,
            ij.scene_id        AS scene_id
        FROM imagery_ingestion_jobs ij
        WHERE ij.requested_at > now() - interval '14 days'
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_integration_recent_attempts")
    # Restore the original (pre-PR-IH2) shape from migration 0019.
    op.execute("DROP VIEW IF EXISTS v_block_integration_health")
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
    op.execute(
        """
        CREATE OR REPLACE VIEW v_farm_integration_health AS
        SELECT
            f.id   AS farm_id,
            f.name AS farm_name,
            COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
              AS weather_active_subs,
            MAX(ws.last_successful_ingest_at) AS weather_last_sync_at,
            MAX(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
              AS imagery_active_subs,
            MAX(ij.requested_at) AS imagery_last_sync_at,
            COUNT(DISTINCT ij.id) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h
        FROM farms f
        LEFT JOIN blocks b ON b.farm_id = f.id AND b.deleted_at IS NULL
        LEFT JOIN weather_subscriptions ws ON ws.block_id = b.id
        LEFT JOIN imagery_aoi_subscriptions ias ON ias.block_id = b.id
        LEFT JOIN imagery_ingestion_jobs ij ON ij.subscription_id = ias.id
        WHERE f.deleted_at IS NULL
        GROUP BY f.id, f.name
        """
    )
    op.execute(
        """
        CREATE OR REPLACE VIEW v_block_integration_health AS
        SELECT
            b.id        AS block_id,
            b.farm_id   AS farm_id,
            b.name      AS block_name,
            COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
              AS weather_active_subs,
            MAX(ws.last_successful_ingest_at) AS weather_last_sync_at,
            MAX(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
              AS imagery_active_subs,
            MAX(ij.requested_at) AS imagery_last_sync_at,
            COUNT(DISTINCT ij.id) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h
        FROM blocks b
        LEFT JOIN weather_subscriptions ws ON ws.block_id = b.id
        LEFT JOIN imagery_aoi_subscriptions ias ON ias.block_id = b.id
        LEFT JOIN imagery_ingestion_jobs ij ON ij.subscription_id = ias.id
        WHERE b.deleted_at IS NULL
        GROUP BY b.id, b.farm_id, b.name
        """
    )
