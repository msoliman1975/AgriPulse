"""usage_daily + usage_flow_daily continuous aggregates.

TEL-6 of docs/proposals/product-telemetry-plan.md.

Why two aggregates and not one
------------------------------
`usage_daily` answers "who used what, where, and how long for". Funnels need a
different grain — `(flow, step)` per session — and folding them into one view
would multiply its cardinality by the step dimension for the 99% of rows that
carry no flow at all.

Why the raw retention (180 d) and the aggregate retention (24 mo) differ
------------------------------------------------------------------------
That difference IS the rollup. Year-over-year adoption is only answerable if
the daily buckets outlive the events they came from, and the buckets are three
orders of magnitude smaller.

Why there is no p95 column
--------------------------
The plan sketched `approx_percentile(0.95, percentile_agg(duration_ms))`. Those
live in `timescaledb_toolkit`, a separate extension. The test image
(`timescale/timescaledb-ha:pg16`) bundles it; production runs
`ghcr.io/imusmanmalik/timescaledb-postgis:16-3.5-115`, which is not the HA image
and is not known to. A migration that works in CI and fails on the cluster is
worse than no percentile, so the aggregate stores `count` / `sum` / `max` — from
which mean is exact — and the p95 query in `telemetry/repository.py` runs
`percentile_cont` over the raw hypertable instead. Raw is 180 days, which is
longer than any latency question is asked about.

Real-time aggregation is left ON (`materialized_only = false`, the default) so
today's partial data appears without waiting for a refresh. That is also
exactly why a tenant purge has to refresh these views — see TEL-6b.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0057"
down_revision: str | Sequence[str] | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `CREATE MATERIALIZED VIEW ... WITH NO DATA` is transaction-safe; it is
    # `refresh_continuous_aggregate` that is not, which is why the view is
    # created empty here and the policy fills it. Same pattern as tenant/0003.
    op.execute(
        """
        CREATE MATERIALIZED VIEW public.usage_daily
        WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 day', time)                AS day,
               tenant_id,
               user_id,
               actor_role,
               is_platform_staff,
               event_name,
               feature,
               route,
               locale,
               count(*)                                  AS events,
               count(*) FILTER (WHERE outcome = 'error') AS errors,
               sum(duration_ms)                          AS total_ms,
               count(duration_ms)                        AS timed_events,
               max(duration_ms)                          AS max_ms
          FROM public.usage_events
         GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
        WITH NO DATA
        """
    )
    op.execute(
        """
        CREATE MATERIALIZED VIEW public.usage_flow_daily
        WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 day', time)                AS day,
               tenant_id,
               is_platform_staff,
               flow,
               step,
               event_name,
               -- No count(DISTINCT session_id): a continuous aggregate cannot
               -- hold a DISTINCT aggregate. Distinct sessions per flow come
               -- from the raw hypertable, which the funnel query has to read
               -- anyway to pair a start with its completion.
               count(*)                                  AS events,
               sum(duration_ms)                          AS total_ms
          FROM public.usage_events
         WHERE flow IS NOT NULL
         GROUP BY 1, 2, 3, 4, 5, 6
        WITH NO DATA
        """
    )

    for view in ("usage_daily", "usage_flow_daily"):
        # start_offset 7 days, not "all of history": events always arrive at
        # `now`, so a rolling window covers every row that can change. The one
        # thing that would break this is a bulk import of historical events —
        # see #336, where backfilled index rows written below the watermark
        # stayed invisible. If we ever import, refresh explicitly over the
        # imported range instead of waiting for the policy.
        op.execute(
            f"""
            SELECT add_continuous_aggregate_policy('public.{view}',
                start_offset      => INTERVAL '7 days',
                end_offset        => INTERVAL '1 hour',
                schedule_interval => INTERVAL '1 hour',
                if_not_exists     => TRUE)
            """
        )
        # 24 months of buckets against 180 days of raw events.
        op.execute(
            f"SELECT add_retention_policy('public.{view}', "
            "INTERVAL '730 days', if_not_exists => TRUE)"
        )

    # The dashboard's own access pattern: a date range, then a tenant.
    op.execute("CREATE INDEX ix_usage_daily_tenant_day ON public.usage_daily (tenant_id, day DESC)")
    op.execute("CREATE INDEX ix_usage_daily_feature_day ON public.usage_daily (feature, day DESC)")
    op.execute(
        "CREATE INDEX ix_usage_flow_daily_flow_day ON public.usage_flow_daily (flow, day DESC)"
    )


def downgrade() -> None:
    # Policies before the view: a live job holding the aggregate makes the DROP
    # fail, exactly as it does for the hypertable in 0056.
    for view in ("usage_flow_daily", "usage_daily"):
        op.execute(f"SELECT remove_retention_policy('public.{view}', if_exists => TRUE)")
        op.execute(
            f"SELECT remove_continuous_aggregate_policy('public.{view}', if_not_exists => TRUE)"
        )
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS public.{view} CASCADE")
