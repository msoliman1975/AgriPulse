"""Right-size the chunking of the two aggregate hypertables.

`block_index_aggregates` and `block_grid_aggregates` were created (0003 /
0034) with `chunk_time_interval => INTERVAL '7 days'` **and** a 4-way
`block_id` space partition. That is 4 chunks per week per table, which
was fine when the tables held a few weeks of data and is badly
over-partitioned now:

    block_index_aggregates, prod, 2026-08-05
      49,126 rows spread over 494 chunks  ->  ~99 rows per chunk

TimescaleDB plans every chunk that a query is not able to exclude, and
chunk exclusion needs a predicate on the time column. The Farm Console's
`/farms/{id}/blocks/summary` asks for "the latest value per (block,
index)", which has no natural time bound, so it planned all 494 chunks:

    Planning Time:  645-1039 ms   (306,986 catalog buffer hits)
    Execution Time: 190-224 ms

Planning, not execution, was the cost — and it grows with every week of
history regardless of how much data those weeks contain.

Two changes, both affecting **new chunks only** (existing chunks keep
their current boundaries and stay readable/compressible exactly as they
are — this migration moves no data and takes no long lock):

  1. `chunk_time_interval` 7 days -> 30 days. TimescaleDB sizes chunks by
     memory footprint, not calendar; at ~100 rows/week these tables are
     three orders of magnitude below the point where 7-day chunks pay off.

  2. `number_partitions` 4 -> 1 on the `block_id` space dimension. Space
     partitioning exists to spread a hypertable across parallel
     tablespaces/data nodes; this is a single-node deployment with a
     single tablespace, so all four partitions live on the same disk and
     the only effect is a 4x multiplier on chunk count.

Together these cut future chunk growth by ~16x. The companion query fix
in `blocks_summary_router.py` bounds the common case in time so it only
plans recent chunks; this migration keeps the *unbounded* fallback path
from degrading again as history accumulates.

Existing chunks are deliberately left alone. Consolidating them would
mean rewriting ~500 compressed chunks, which is a maintenance operation
to run deliberately against a specific tenant, not something to do inside
a migration that runs unattended against every tenant schema.

Revision ID: 0057
Revises: 0056
Create Date: 2026-08-05
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("block_index_aggregates", "block_grid_aggregates")

_NEW_CHUNK_INTERVAL = "30 days"
_OLD_CHUNK_INTERVAL = "7 days"
_NEW_PARTITIONS = 1
_OLD_PARTITIONS = 4


def _apply(*, chunk_interval: str, partitions: int) -> None:
    for table in _TABLES:
        # to_regclass keeps this a no-op on a schema where the table does
        # not exist yet, matching the if_not_exists posture of 0003/0034.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('{table}') IS NOT NULL THEN
                    PERFORM set_chunk_time_interval(
                        '{table}'::regclass, INTERVAL '{chunk_interval}');
                    PERFORM set_number_partitions(
                        '{table}'::regclass, {partitions}, 'block_id');
                END IF;
            END $$;
            """
        )


def upgrade() -> None:
    _apply(chunk_interval=_NEW_CHUNK_INTERVAL, partitions=_NEW_PARTITIONS)


def downgrade() -> None:
    _apply(chunk_interval=_OLD_CHUNK_INTERVAL, partitions=_OLD_PARTITIONS)
