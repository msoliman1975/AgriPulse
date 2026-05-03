"""Flip block_index_daily / block_index_weekly to real-time aggregation.

PR-A's 0003 created the two continuous aggregates with
`materialized_only=true` (the default), which means freshly-written
rows in `block_index_aggregates` aren't visible to the timeseries
endpoint until the hourly refresh policy fires. PR-C's `compute_indices`
task writes a row at ingestion time and the API needs to surface it
immediately — flipping `materialized_only=false` lets TimescaleDB
merge the materialized buckets with the latest hypertable rows on
read, with no per-write overhead.

Real-time aggregation has a small read-side cost (TimescaleDB scans
the hypertable for rows newer than the last materialized bucket on
every query) — at our row rate (six rows per scene per block) that's
trivial.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER MATERIALIZED VIEW block_index_daily " "SET (timescaledb.materialized_only = false)"
    )
    op.execute(
        "ALTER MATERIALIZED VIEW block_index_weekly " "SET (timescaledb.materialized_only = false)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER MATERIALIZED VIEW block_index_weekly " "SET (timescaledb.materialized_only = true)"
    )
    op.execute(
        "ALTER MATERIALIZED VIEW block_index_daily " "SET (timescaledb.materialized_only = true)"
    )
