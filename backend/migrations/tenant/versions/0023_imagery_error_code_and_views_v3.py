"""imagery error_code column + Runs-view split of queue-wait vs run-time.

PR-IH8.

Adds `imagery_ingestion_jobs.error_code` so failures can be grouped/
filtered the same way weather attempts already are. Mirrors
`weather_ingestion_attempts.error_code` — a short categorized label
like `'tls_trust'`, `'http_4xx'`, `'timeout'`, etc.

Rebuilds `v_integration_recent_attempts` to expose the new column
**and** split the misleading single `duration_ms` into:

  - `started_at`  — when the worker actually picked the job up
                    (was previously `requested_at` for imagery — see
                     the runbook ticket about a 16h "duration" that was
                     really queue-wait stacked on top of retries).
  - `queued_at`   — when the job entered the queue.
  - `wait_ms`     — queue → start latency.
  - `run_ms`      — start → complete latency.

The single `duration_ms` stays for backward-compat (now strictly equals
`run_ms`); consumers can migrate to the explicit pair.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "imagery_ingestion_jobs",
        sa.Column("error_code", sa.Text(), nullable=True),
    )

    # Drop + recreate the union view with new columns. CREATE OR REPLACE
    # would refuse because we're adding output columns *in the middle* of
    # the column list (Postgres only allows OR REPLACE when appending).
    op.execute("DROP VIEW IF EXISTS v_integration_recent_attempts")
    op.execute(
        """
        CREATE VIEW v_integration_recent_attempts AS
        SELECT
            wa.id              AS attempt_id,
            'weather'::text    AS kind,
            wa.subscription_id AS subscription_id,
            wa.block_id        AS block_id,
            wa.farm_id         AS farm_id,
            wa.provider_code   AS provider_code,
            wa.started_at      AS started_at,
            -- Weather has no queue: started_at == queued_at conceptually.
            wa.started_at      AS queued_at,
            wa.completed_at    AS completed_at,
            wa.status          AS status,
            wa.duration_ms     AS duration_ms,
            0                  AS wait_ms,
            wa.duration_ms     AS run_ms,
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
            -- For imagery, started_at is when a worker picked the job up;
            -- requested_at is when it entered the queue. Previous version of
            -- this view conflated the two — see PR-IH8.
            COALESCE(ij.started_at, ij.requested_at) AS started_at,
            ij.requested_at    AS queued_at,
            ij.completed_at    AS completed_at,
            CASE
              WHEN ij.status IN ('pending', 'requested') THEN 'running'
              ELSE ij.status
            END                AS status,
            -- Legacy duration_ms == run_ms now; kept for older clients.
            CASE
              WHEN ij.completed_at IS NULL OR ij.started_at IS NULL THEN NULL
              ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                       (ij.completed_at - ij.started_at)) * 1000)::int)
            END                AS duration_ms,
            CASE
              WHEN ij.started_at IS NULL THEN NULL
              ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                       (ij.started_at - ij.requested_at)) * 1000)::int)
            END                AS wait_ms,
            CASE
              WHEN ij.completed_at IS NULL OR ij.started_at IS NULL THEN NULL
              ELSE GREATEST(0, (EXTRACT(EPOCH FROM
                       (ij.completed_at - ij.started_at)) * 1000)::int)
            END                AS run_ms,
            NULL::int          AS rows_ingested,
            ij.error_code      AS error_code,
            ij.error_message   AS error_message,
            ij.scene_id        AS scene_id
        FROM imagery_ingestion_jobs ij
        WHERE ij.requested_at > now() - interval '14 days'
        """
    )


def downgrade() -> None:
    # Recreate the pre-IH8 view shape and drop the column.
    op.execute("DROP VIEW IF EXISTS v_integration_recent_attempts")
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
            (SELECT ip.code FROM public.imagery_products ip WHERE ip.id = ij.product_id)
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
    op.drop_column("imagery_ingestion_jobs", "error_code")
