"""weather_ingestion_attempts — per-attempt history for weather ingestion.

Imagery already has `imagery_ingestion_jobs` as its per-run log. Weather
only stored `last_successful_ingest_at` + `last_attempted_at` on the
subscription, so a failed sync left no row anywhere. This adds an
attempt log so the integrations-health UI can answer "why did it fail?"
and not just "is it stale?".

One row per `fetch_weather` invocation per touched subscription. The
fetch task groups subscriptions by (farm, provider), so a single
provider call yields N attempt rows (one per active subscription on the
farm) — that matches the existing `touch_subscription_attempt` shape so
each block's history is independently queryable.

Retention: 14 days, matching the Slice-4 forecast-retention lock. The
prune is handled by a Celery beat task added in a later PR; this
migration only defines the table.

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weather_ingestion_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        # Denormalized so the runs tab + queue view can filter on
        # block/farm/provider without joining back to subscriptions.
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_code", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # 'running' rows that never completed end up as "stuck" via the
        # health views' `*_running_count` + a started_at threshold.
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("rows_ingested", sa.Integer(), nullable=True),
        # error_code is a short categorized label ('http_error', 'timeout',
        # 'provider_5xx', 'parse_error', ...). error_message is the raw
        # provider string, truncated by the writer to keep rows compact.
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Generated column — Postgres 12+. Always-stored so indexable.
        sa.Column(
            "duration_ms",
            sa.Integer(),
            sa.Computed(
                "CASE WHEN completed_at IS NULL THEN NULL "
                "ELSE GREATEST(0, "
                "(EXTRACT(EPOCH FROM (completed_at - started_at)) * 1000)::int) "
                "END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["weather_subscriptions.id"],
            name="fk_weather_ingestion_attempts_subscription_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'skipped')",
            name="ck_weather_ingestion_attempts_status_valid",
        ),
    )
    # Drill-down: "give me the last N attempts for this block."
    op.create_index(
        "ix_weather_ingestion_attempts_block_started",
        "weather_ingestion_attempts",
        ["block_id", sa.text("started_at DESC")],
    )
    # Queue + failure dashboards: scan only running/failed without
    # filtering through the bulk of succeeded rows.
    op.create_index(
        "ix_weather_ingestion_attempts_status_started",
        "weather_ingestion_attempts",
        ["status", sa.text("started_at DESC")],
        postgresql_where=sa.text("status IN ('running', 'failed')"),
    )
    # Subscription drill-down + cascade index.
    op.create_index(
        "ix_weather_ingestion_attempts_subscription_started",
        "weather_ingestion_attempts",
        ["subscription_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_weather_ingestion_attempts_subscription_started",
        table_name="weather_ingestion_attempts",
    )
    op.drop_index(
        "ix_weather_ingestion_attempts_status_started",
        table_name="weather_ingestion_attempts",
    )
    op.drop_index(
        "ix_weather_ingestion_attempts_block_started",
        table_name="weather_ingestion_attempts",
    )
    op.drop_table("weather_ingestion_attempts")
