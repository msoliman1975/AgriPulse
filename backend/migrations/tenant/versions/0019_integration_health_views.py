"""Integration health views — per-Farm and per-Block sync status.

Read-only SQL views over existing weather/imagery state. Lets the
Settings → Integrations tab show "weather last synced 14m ago,
imagery had 2 failed jobs in the last 24h" without each route
re-implementing the join.

Two views per tenant schema:

  v_farm_integration_health  — one row per Farm, aggregates over its
                               blocks' subscriptions + ingestion jobs.
  v_block_integration_health — one row per Block, raw without aggregation.

No new write paths. Drop both on downgrade.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # imagery_ingestion_jobs uses `requested_at` for the create timestamp,
    # not `created_at`; status values include 'failed' for failed runs.
    op.execute(
        """
        CREATE OR REPLACE VIEW v_farm_integration_health AS
        SELECT
            f.id   AS farm_id,
            f.name AS farm_name,
            -- weather
            COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
              AS weather_active_subs,
            MAX(ws.last_successful_ingest_at)
              AS weather_last_sync_at,
            MAX(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            -- imagery
            COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
              AS imagery_active_subs,
            MAX(ij.requested_at)
              AS imagery_last_sync_at,
            COUNT(DISTINCT ij.id) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h
        FROM farms f
        LEFT JOIN blocks b
          ON b.farm_id = f.id AND b.deleted_at IS NULL
        LEFT JOIN weather_subscriptions ws
          ON ws.block_id = b.id
        LEFT JOIN imagery_aoi_subscriptions ias
          ON ias.block_id = b.id
        LEFT JOIN imagery_ingestion_jobs ij
          ON ij.subscription_id = ias.id
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
            -- weather (one block can have several subscriptions; take aggregates)
            COUNT(DISTINCT ws.id) FILTER (WHERE ws.is_active)
              AS weather_active_subs,
            MAX(ws.last_successful_ingest_at)
              AS weather_last_sync_at,
            MAX(ws.last_attempted_at) FILTER
              (WHERE ws.last_attempted_at >
                     COALESCE(ws.last_successful_ingest_at, '-infinity'::timestamptz))
              AS weather_last_failed_at,
            -- imagery
            COUNT(DISTINCT ias.id) FILTER (WHERE ias.is_active)
              AS imagery_active_subs,
            MAX(ij.requested_at)
              AS imagery_last_sync_at,
            COUNT(DISTINCT ij.id) FILTER
              (WHERE ij.status = 'failed'
                AND ij.requested_at > now() - interval '24 hours')
              AS imagery_failed_24h
        FROM blocks b
        LEFT JOIN weather_subscriptions ws
          ON ws.block_id = b.id
        LEFT JOIN imagery_aoi_subscriptions ias
          ON ias.block_id = b.id
        LEFT JOIN imagery_ingestion_jobs ij
          ON ij.subscription_id = ias.id
        WHERE b.deleted_at IS NULL
        GROUP BY b.id, b.farm_id, b.name
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_block_integration_health")
    op.execute("DROP VIEW IF EXISTS v_farm_integration_health")
