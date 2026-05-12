"""Add `failed_streak_position` to v_integration_recent_attempts.

PR-IH9.

For each row, computes "how many consecutive failures preceded this
one (inclusive) on the same subscription". The Runs tab renders this
as "Attempt #N" when N > 1 so the operator can tell a single transient
blip apart from a persistent failure.

Semantics for the returned int:
  - 0           — this row is not a failure (succeeded / skipped /
                  running), or no preceding history exists.
  - 1           — first failure in a streak.
  - N (>1)      — Nth consecutive failure in the current streak.

Implementation. Each side of the UNION computes its own streak
window. Successes "reset" the streak. The streak id is a running sum
of preceding successes — every failure shares the streak id of the
last preceding success (or 0 if none), so consecutive failures
naturally cluster by (subscription_id, streak_id).

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_integration_recent_attempts")
    op.execute(
        """
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
    )


def downgrade() -> None:
    # Restore pre-IH9 view (the IH8 shape, without failed_streak_position).
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
            (SELECT ip.code FROM public.imagery_products ip WHERE ip.id = ij.product_id)
                               AS provider_code,
            COALESCE(ij.started_at, ij.requested_at) AS started_at,
            ij.requested_at    AS queued_at,
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
