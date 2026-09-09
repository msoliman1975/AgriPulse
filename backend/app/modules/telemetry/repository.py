"""Read queries over `usage_events` and its two continuous aggregates.

TEL-6. Every query here answers one of the questions in §8/§9 of
docs/proposals/product-telemetry-plan.md, and each is written so the answer is a
number, not an impression.

Three rules hold across all of them:

1. **Platform staff are excluded by default.** On a pilot-scale product we are
   the top user; a chart that includes our own clicking is not describing the
   customer. `include_staff=True` exists for debugging our own instrumentation.
2. **Bind real objects.** Dates go in as `date`/`datetime`, ids as `UUID`. The
   #331/#332/#335 bug family is a string bound through a `CAST(... AS ...)`;
   there is not one in this file and there must not be.
3. **Read the aggregate when the aggregate answers it.** `usage_daily` covers
   24 months and is far smaller than raw. Raw is read only for the questions the
   aggregate structurally cannot answer: distinct sessions, pairing a flow start
   with its completion, and percentiles.
4. **Cast `day` to `date` at the edge.** The aggregate's `day` column is
   `time_bucket('1 day', time)` over a `timestamptz`, so it comes back as a
   midnight `timestamptz`, not a `date`. The response models declare `date`, and
   Pydantic will quietly coerce a midnight datetime — which means the contract
   would be true by luck rather than by construction, and any consumer comparing
   to a real `date` gets a surprise. `::date` makes it true.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# `is_platform_staff` is a real boolean column, so the exclusion is a plain
# predicate rather than a formatted fragment. Kept as a constant so no query can
# quietly forget it.
_EXCLUDE_STAFF = "AND is_platform_staff = false"


@dataclass(frozen=True)
class UsageWindow:
    """The filter every dashboard query shares.

    `start`/`end` are dates, not timestamps: the aggregate buckets by day, and a
    half-open timestamp range would silently drop the last partial day.
    """

    start: date
    end: date
    tenant_id: UUID | None = None
    include_staff: bool = False

    def params(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "tenant_id": self.tenant_id}


def _staff_clause(window: UsageWindow) -> str:
    return "" if window.include_staff else _EXCLUDE_STAFF


def _tenant_clause() -> str:
    # `:tenant_id IS NULL OR tenant_id = :tenant_id` in one predicate keeps the
    # parameter set identical whether or not a tenant is selected, which is what
    # lets every query below share `UsageWindow.params()`.
    return "AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = :tenant_id)"


class TelemetryRepository:
    """Read-only. Nothing in this class writes; ingest owns the write path."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # -- engagement ---------------------------------------------------------

    async def active_users(self, window: UsageWindow) -> dict[str, int]:
        """DAU / WAU / MAU as of `window.end`.

        Deliberately anchored on `end` rather than computed per day: these are
        headline numbers for one moment. A per-day series is a different, and
        much more expensive, question — `daily_activity` answers that one.
        """
        row = (
            await self._s.execute(
                text(
                    f"""
                    SELECT
                      count(DISTINCT user_id) FILTER (
                        WHERE day > CAST(:end AS date) - 1)  AS dau,
                      count(DISTINCT user_id) FILTER (
                        WHERE day > CAST(:end AS date) - 7)  AS wau,
                      count(DISTINCT user_id) FILTER (
                        WHERE day > CAST(:end AS date) - 30) AS mau
                    FROM public.usage_daily
                    WHERE day >= CAST(:end AS date) - 30
                      AND day <= :end
                      AND user_id IS NOT NULL
                      {_tenant_clause()}
                      {_staff_clause(window)}
                    """
                ),
                window.params(),
            )
        ).one()
        return {"dau": int(row[0] or 0), "wau": int(row[1] or 0), "mau": int(row[2] or 0)}

    async def session_stats(self, window: UsageWindow) -> dict[str, float]:
        """Median session length, session count, sessions per user.

        Session length is the span between a session's first and last event.
        `session_end` fires on idle or tab close and is not reliable — deriving
        the span from events we definitely have is more honest than trusting one
        the browser may never send.

        Raw, not the aggregate: a session is a DISTINCT dimension the aggregate
        cannot hold.
        """
        row = (
            await self._s.execute(
                text(
                    f"""
                    WITH spans AS (
                        SELECT session_id,
                               user_id,
                               EXTRACT(EPOCH FROM (max(time) - min(time))) AS seconds
                          FROM public.usage_events
                         WHERE time >= :start AND time < CAST(:end AS date) + 1
                           {_tenant_clause()}
                           {_staff_clause(window)}
                         GROUP BY session_id, user_id
                    )
                    SELECT
                      percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds) AS median_seconds,
                      count(*)                                             AS sessions,
                      count(DISTINCT user_id)                              AS users
                    FROM spans
                    """
                ),
                window.params(),
            )
        ).one()
        sessions = int(row[1] or 0)
        users = int(row[2] or 0)
        return {
            "median_session_seconds": float(row[0] or 0.0),
            "sessions": float(sessions),
            "sessions_per_user": (sessions / users) if users else 0.0,
        }

    # -- where time goes ----------------------------------------------------

    async def time_by_route(self, window: UsageWindow, limit: int = 15) -> list[dict[str, Any]]:
        """Top routes by total VISIBLE dwell, with the median visit.

        `total_ms` comes from the aggregate; the median needs raw rows, because
        a median cannot be assembled from daily sums. Two reads rather than one
        is the honest cost of a median — a mean here would be dominated by the
        long tail of tabs left open.
        """
        totals = (
            await self._s.execute(
                text(
                    f"""
                    SELECT route,
                           sum(total_ms)     AS total_ms,
                           sum(timed_events) AS visits
                      FROM public.usage_daily
                     WHERE day >= :start AND day <= :end
                       AND event_name = 'page_leave'
                       AND route IS NOT NULL
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     GROUP BY route
                     ORDER BY sum(total_ms) DESC NULLS LAST
                     LIMIT :limit
                    """
                ),
                {**window.params(), "limit": limit},
            )
        ).all()
        if not totals:
            return []

        routes = [r[0] for r in totals]
        medians = {
            r[0]: r[1]
            for r in (
                await self._s.execute(
                    text(
                        f"""
                        SELECT route,
                               percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)
                          FROM public.usage_events
                         WHERE time >= :start AND time < CAST(:end AS date) + 1
                           AND event_name = 'page_leave'
                           AND duration_ms IS NOT NULL
                           AND route = ANY(:routes)
                           {_tenant_clause()}
                           {_staff_clause(window)}
                         GROUP BY route
                        """
                    ),
                    {**window.params(), "routes": routes},
                )
            ).all()
        }
        return [
            {
                "route": r[0],
                "total_ms": int(r[1] or 0),
                "visits": int(r[2] or 0),
                "median_ms": int(medians.get(r[0]) or 0),
            }
            for r in totals
        ]

    # -- capability adoption ------------------------------------------------

    async def feature_adoption(self, window: UsageWindow) -> list[dict[str, Any]]:
        """One row per feature actually used: events, users, tenants reached."""
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT feature,
                           sum(events)               AS events,
                           count(DISTINCT user_id)   AS users,
                           count(DISTINCT tenant_id) AS tenants,
                           max(day)::date            AS last_used
                      FROM public.usage_daily
                     WHERE day >= :start AND day <= :end
                       AND event_name = 'feature_used'
                       AND feature IS NOT NULL
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     GROUP BY feature
                     ORDER BY sum(events) DESC
                    """
                ),
                window.params(),
            )
        ).all()
        return [
            {
                "feature": r[0],
                "events": int(r[1] or 0),
                "users": int(r[2] or 0),
                "tenants": int(r[3] or 0),
                "last_used": r[4],
            }
            for r in rows
        ]

    async def cold_features(self, known: list[str], window: UsageWindow) -> list[str]:
        """Features in the enum with zero use in the window.

        `known` comes from the taxonomy, not from the table, and that is the
        whole point: a capability nobody has ever used produces no rows at all,
        so a query over the data alone can never name it. This is the one
        question that has to be asked against the vocabulary.
        """
        used = {row["feature"] for row in await self.feature_adoption(window)}
        return sorted(f for f in known if f not in used)

    # -- funnels ------------------------------------------------------------

    async def flow_funnel(self, window: UsageWindow) -> list[dict[str, Any]]:
        """Per flow: entries, completions, and where the rest died.

        Abandonment is DERIVED — a `flow_start` with no `flow_complete` for that
        `(session_id, flow)`. The client cannot report it: the case that matters
        most is the user who closed the laptop, and they send nothing.
        """
        rows = (
            await self._s.execute(
                text(
                    f"""
                    WITH scoped AS (
                        SELECT session_id, flow, step, event_name, time
                          FROM public.usage_events
                         WHERE time >= :start AND time < CAST(:end AS date) + 1
                           AND flow IS NOT NULL
                           {_tenant_clause()}
                           {_staff_clause(window)}
                    ),
                    starts AS (
                        SELECT DISTINCT session_id, flow
                          FROM scoped WHERE event_name = 'flow_start'
                    ),
                    completes AS (
                        SELECT DISTINCT session_id, flow
                          FROM scoped WHERE event_name = 'flow_complete'
                    ),
                    last_step AS (
                        SELECT DISTINCT ON (session_id, flow) session_id, flow, step
                          FROM scoped
                         WHERE event_name = 'flow_step' AND step IS NOT NULL
                         ORDER BY session_id, flow, time DESC
                    )
                    SELECT s.flow,
                           count(*)                                     AS entries,
                           count(c.session_id)                          AS completions,
                           count(*) FILTER (WHERE c.session_id IS NULL) AS abandoned,
                           mode() WITHIN GROUP (
                             ORDER BY CASE WHEN c.session_id IS NULL
                                           THEN l.step END)             AS died_at
                      FROM starts s
                      LEFT JOIN completes c USING (session_id, flow)
                      LEFT JOIN last_step l USING (session_id, flow)
                     GROUP BY s.flow
                     ORDER BY count(*) DESC
                    """  # noqa: S608 - interpolates module constants only, never input
                ),
                window.params(),
            )
        ).all()
        return [
            {
                "flow": r[0],
                "entries": int(r[1] or 0),
                "completions": int(r[2] or 0),
                "abandoned": int(r[3] or 0),
                # NULL means the abandoning sessions left before their first
                # flow_step, which is itself the answer: they bounced at entry.
                "died_at": r[4],
            }
            for r in rows
        ]

    async def flow_steps(self, window: UsageWindow) -> list[dict[str, Any]]:
        """Sessions reaching each step, for the per-step drop-off bars."""
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT flow, step, count(DISTINCT session_id) AS sessions
                      FROM public.usage_events
                     WHERE time >= :start AND time < CAST(:end AS date) + 1
                       AND event_name = 'flow_step'
                       AND flow IS NOT NULL AND step IS NOT NULL
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     GROUP BY flow, step
                     ORDER BY flow, count(DISTINCT session_id) DESC
                    """  # noqa: S608 - interpolates module constants only, never input
                ),
                window.params(),
            )
        ).all()
        return [{"flow": r[0], "step": r[1], "sessions": int(r[2] or 0)} for r in rows]

    # -- struggle -----------------------------------------------------------

    async def error_dense_routes(
        self, window: UsageWindow, min_views: int = 20
    ) -> list[dict[str, Any]]:
        """Errors per page view, by route. The headline struggle signal.

        `min_views` exists because a route with 2 views and 1 error is 50% and
        means nothing. Without a floor the board is permanently topped by noise.
        """
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT route,
                           sum(events) FILTER (WHERE event_name = 'page_view')  AS views,
                           sum(events) FILTER (
                             WHERE event_name IN ('api_error', 'client_error')) AS errors
                      FROM public.usage_daily
                     WHERE day >= :start AND day <= :end
                       AND route IS NOT NULL
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     GROUP BY route
                    HAVING sum(events) FILTER (WHERE event_name = 'page_view') >= :min_views
                       AND sum(events) FILTER (
                             WHERE event_name IN ('api_error', 'client_error')) > 0
                     ORDER BY (
                       sum(events) FILTER (
                         WHERE event_name IN ('api_error', 'client_error'))::float
                       / NULLIF(sum(events) FILTER (WHERE event_name = 'page_view'), 0)
                     ) DESC
                     LIMIT 20
                    """
                ),
                {**window.params(), "min_views": min_views},
            )
        ).all()
        return [
            {
                "route": r[0],
                "views": int(r[1] or 0),
                "errors": int(r[2] or 0),
                "error_rate": (int(r[2] or 0) / int(r[1])) if r[1] else 0.0,
            }
            for r in rows
        ]

    async def recent_errors(
        self, window: UsageWindow, route: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Recent failures with their `correlation_id`.

        This is the query that closes the loop: it hands you the id that finds
        the server log line and the trace for a failure a real user saw. Without
        it the dashboard can say a route is broken but never why.
        """
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT time, route, status_code, error_code, correlation_id,
                           props ->> 'method' AS method
                      FROM public.usage_events
                     WHERE time >= :start AND time < CAST(:end AS date) + 1
                       AND event_name IN ('api_error', 'client_error')
                       AND (CAST(:route AS text) IS NULL OR route = :route)
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     ORDER BY time DESC
                     LIMIT :limit
                    """
                ),
                {**window.params(), "route": route, "limit": limit},
            )
        ).all()
        return [
            {
                "time": r[0],
                "route": r[1],
                "status_code": r[2],
                "error_code": r[3],
                "correlation_id": r[4],
                "method": r[5],
            }
            for r in rows
        ]

    async def retry_storms(self, window: UsageWindow, limit: int = 20) -> list[dict[str, Any]]:
        """Three or more identical actions inside 60 s.

        A user repeating the same click is telling us the click did not appear
        to work. Grouped by (user, feature, action), so "clicked Save on two
        different blocks" is not miscounted as a storm.
        """
        rows = (
            await self._s.execute(
                text(
                    f"""
                    WITH acts AS (
                        SELECT user_id, feature, props ->> 'action' AS action, time,
                               lag(time, 2) OVER (
                                 PARTITION BY user_id, feature, props ->> 'action'
                                 ORDER BY time) AS third_back
                          FROM public.usage_events
                         WHERE time >= :start AND time < CAST(:end AS date) + 1
                           AND event_name = 'feature_used'
                           AND user_id IS NOT NULL
                           {_tenant_clause()}
                           {_staff_clause(window)}
                    )
                    SELECT feature, action, count(*) AS storms,
                           count(DISTINCT user_id) AS users
                      FROM acts
                     WHERE third_back IS NOT NULL
                       AND time - third_back <= INTERVAL '60 seconds'
                     GROUP BY feature, action
                     ORDER BY count(*) DESC
                     LIMIT :limit
                    """
                ),
                {**window.params(), "limit": limit},
            )
        ).all()
        return [
            {
                "feature": r[0],
                "action": r[1],
                "storms": int(r[2] or 0),
                "users": int(r[3] or 0),
            }
            for r in rows
        ]

    async def slow_actions(
        self, window: UsageWindow, threshold_ms: int = 3000
    ) -> list[dict[str, Any]]:
        """p95 perceived latency per feature, at or over the threshold.

        `percentile_cont` over raw, not the aggregate — see migration 0083 for
        why there is no p95 column.
        """
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT feature,
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
                           count(*) AS samples
                      FROM public.usage_events
                     WHERE time >= :start AND time < CAST(:end AS date) + 1
                       AND event_name = 'feature_used'
                       AND duration_ms IS NOT NULL
                       AND feature IS NOT NULL
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     GROUP BY feature
                    HAVING percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                           >= :threshold_ms
                     ORDER BY 2 DESC
                    """
                ),
                {**window.params(), "threshold_ms": threshold_ms},
            )
        ).all()
        return [
            {"feature": r[0], "p95_ms": int(r[1] or 0), "samples": int(r[2] or 0)} for r in rows
        ]

    # -- tenant health ------------------------------------------------------

    async def tenant_health(self, window: UsageWindow) -> list[dict[str, Any]]:
        """Per tenant: last seen, weekly actives, breadth of use.

        `features_used` is the breadth signal. A tenant using two capabilities
        is a different retention risk from one using twelve, even at the same
        event count.

        Platform staff are excluded unconditionally here, not by the window
        flag: staff rows carry no tenant_id, so including them would only add a
        NULL group that means nothing on a per-tenant table.
        """
        rows = (
            await self._s.execute(
                text(
                    """
                    SELECT tenant_id,
                           max(day)::date                          AS last_seen,
                           count(DISTINCT user_id) FILTER (
                             WHERE day > CAST(:end AS date) - 7)   AS wau,
                           count(DISTINCT feature)                 AS features_used,
                           sum(events)                             AS events
                      FROM public.usage_daily
                     WHERE day >= :start AND day <= :end
                       AND tenant_id IS NOT NULL
                       AND is_platform_staff = false
                       AND (CAST(:tenant_id AS uuid) IS NULL OR tenant_id = :tenant_id)
                     GROUP BY tenant_id
                     ORDER BY max(day) DESC
                    """
                ),
                window.params(),
            )
        ).all()
        return [
            {
                "tenant_id": r[0],
                "last_seen": r[1],
                "wau": int(r[2] or 0),
                "features_used": int(r[3] or 0),
                "events": int(r[4] or 0),
            }
            for r in rows
        ]

    # -- daily series -------------------------------------------------------

    async def daily_activity(self, window: UsageWindow) -> list[dict[str, Any]]:
        """Events and distinct users per day — the sparkline behind the KPIs."""
        rows = (
            await self._s.execute(
                text(
                    f"""
                    SELECT day::date AS day,
                           sum(events)             AS events,
                           count(DISTINCT user_id) AS users
                      FROM public.usage_daily
                     WHERE day >= :start AND day <= :end
                       {_tenant_clause()}
                       {_staff_clause(window)}
                     GROUP BY day
                     ORDER BY day
                    """
                ),
                window.params(),
            )
        ).all()
        return [{"day": r[0], "events": int(r[1] or 0), "users": int(r[2] or 0)} for r in rows]
