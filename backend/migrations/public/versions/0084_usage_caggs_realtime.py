"""Turn real-time aggregation ON for the two usage aggregates.

0083 created `usage_daily` and `usage_flow_daily` believing that
`timescaledb.materialized_only` defaults to **false** — the plan says so, and
0083's own docstring repeats it: "Real-time aggregation is left ON
(`materialized_only = false`, the default) so today's partial data appears
without waiting for a refresh."

That was true once. **The default flipped to `true` in TimescaleDB 2.13**, and
this cluster runs 2.26.4. So both views shipped with real-time aggregation OFF
and returned only materialised buckets.

What that looked like in production: 74 raw events in `usage_events`, and zero
rows from `usage_daily`. The dashboard's KPI row, dwell table, adoption table
and tenant health all read the aggregate, so they were empty while the raw data
was plainly there. Because the refresh policy also carries `end_offset => 1
hour`, the page would never have shown the current hour at all — the exact
property 0083 claimed to deliver.

Turning it back on makes the view read as
`materialised buckets UNION ALL aggregate(raw rows newer than the watermark)`,
so new events show immediately.

**`end_offset` is deliberately left at 1 hour.** With real-time aggregation on,
it no longer controls what the reader sees — only how far behind the background
materialisation runs. Dropping it to zero would re-materialise the current,
still-filling bucket on every run for no benefit. That is a correction to my
first instinct here: the 1-hour offset was never the bug, the flag was.

No data migration. Materialised buckets stay valid; only the read path changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0084"
down_revision: str | Sequence[str] | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VIEWS = ("usage_daily", "usage_flow_daily")


def upgrade() -> None:
    for view in _VIEWS:
        op.execute(
            f"ALTER MATERIALIZED VIEW public.{view} SET (timescaledb.materialized_only = false)"
        )


def downgrade() -> None:
    # Back to what 0083 actually produced on TimescaleDB >= 2.13, not to what it
    # meant to produce. A downgrade that restored the intent rather than the
    # state would leave the database in a shape no forward migration ever built.
    for view in _VIEWS:
        op.execute(
            f"ALTER MATERIALIZED VIEW public.{view} SET (timescaledb.materialized_only = true)"
        )
