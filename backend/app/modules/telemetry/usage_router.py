"""The usage dashboard's read API (TEL-6 / TEL-7).

    GET /api/v1/platform/usage/overview

Separate router from `router.py` on purpose. Ingest is open to every
authenticated user and answers 202 whatever happens; this is gated by
`platform.read_usage` and answers honestly, because a chart that silently
returns zeros is worse than an error — it reads as "nobody uses this".

Everything comes back in one response. The page shows all of it at once, and
seven round trips would each re-scan the same window for no benefit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.read_schemas import (
    EngagementKpis,
    UsageFilterOptions,
    UsageFilters,
    UsageOverview,
)
from app.modules.telemetry.repository import TelemetryRepository, UsageWindow
from app.modules.telemetry.taxonomy import get_taxonomy
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/platform/usage", tags=["platform-usage"])

_ReadUsage = Depends(requires_capability("platform.read_usage"))

# 180 days is the raw retention. Asking for more silently returns a window with
# a hole in it, so the bound is enforced rather than left to the caller.
MAX_WINDOW_DAYS = 180


@router.get(
    "/overview",
    response_model=UsageOverview,
    dependencies=[_ReadUsage],
    summary="Engagement, adoption, funnels and struggle signals for one window",
)
async def usage_overview(
    start: date | None = Query(default=None, description="Inclusive. Defaults to end - 29 days."),
    end: date | None = Query(default=None, description="Inclusive. Defaults to today, UTC."),
    tenant_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(
        default=None,
        description=(
            "Narrow to one person. Every section honours it, so the page becomes "
            "a per-user view rather than a filtered summary."
        ),
    ),
    include_staff: bool = Query(
        default=False,
        description=(
            "Include platform staff. Off by default: on a pilot-scale product our "
            "own clicking outweighs the customers' and every chart would lie."
        ),
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> UsageOverview:
    window = _window(
        start=start,
        end=end,
        tenant_id=tenant_id,
        user_id=user_id,
        include_staff=include_staff,
    )
    repo = TelemetryRepository(session)

    actives = await repo.active_users(window)
    sessions = await repo.session_stats(window)
    wau = actives["wau"]

    return UsageOverview(
        filters=UsageFilters(
            start=window.start,
            end=window.end,
            tenant_id=window.tenant_id,
            user_id=window.user_id,
            include_staff=window.include_staff,
        ),
        kpis=EngagementKpis(
            dau=actives["dau"],
            wau=wau,
            mau=actives["mau"],
            # Guarded: with no traffic at all this is 0/0, and a page that
            # 500s on an empty database is a page nobody trusts on day one.
            stickiness=(actives["dau"] / wau) if wau else 0.0,
            median_session_seconds=sessions["median_session_seconds"],
            sessions=int(sessions["sessions"]),
            sessions_per_user=sessions["sessions_per_user"],
        ),
        daily=await repo.daily_activity(window),
        routes=await repo.time_by_route(window),
        features=await repo.feature_adoption(window),
        cold_features=await repo.cold_features(sorted(get_taxonomy().features), window),
        funnels=await repo.flow_funnel(window),
        funnel_steps=await repo.flow_steps(window),
        error_routes=await repo.error_dense_routes(window),
        recent_errors=await repo.recent_errors(window),
        retry_storms=await repo.retry_storms(window),
        slow_actions=await repo.slow_actions(window),
        tenants=await repo.tenant_health(window),
    )


@router.get(
    "/filters",
    response_model=UsageFilterOptions,
    dependencies=[_ReadUsage],
    summary="Tenants and people that appear in this window, for the pickers",
)
async def usage_filters(
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    tenant_id: UUID | None = Query(
        default=None,
        description="Narrows the people list to that tenant's users.",
    ),
    include_staff: bool = Query(default=False),
    session: AsyncSession = Depends(get_admin_db_session),
) -> UsageFilterOptions:
    """Separate from /overview on purpose.

    The option lists change far more slowly than the numbers do, so they get
    their own cache instead of being re-fetched every time someone moves the
    date range. Folding them into the overview would also mean re-reading a
    500-row user list to answer "how many people used it yesterday".
    """
    window = _window(
        start=start, end=end, tenant_id=tenant_id, user_id=None, include_staff=include_staff
    )
    options = await TelemetryRepository(session).filter_options(window)
    return UsageFilterOptions(**options)


def _window(
    *,
    start: date | None,
    end: date | None,
    tenant_id: UUID | None,
    user_id: UUID | None,
    include_staff: bool,
) -> UsageWindow:
    """Resolve the date range, clamped to what the data can actually answer.

    Clamping rather than erroring: the page's date picker is the only caller,
    and a 422 on a range one day too wide is a worse experience than 180 days
    of data with the range echoed back in `filters`.
    """
    resolved_end = end or datetime.now(UTC).date()
    resolved_start = start or (resolved_end - timedelta(days=29))
    resolved_start = min(resolved_start, resolved_end)
    if (resolved_end - resolved_start).days > MAX_WINDOW_DAYS:
        resolved_start = resolved_end - timedelta(days=MAX_WINDOW_DAYS)
    return UsageWindow(
        start=resolved_start,
        end=resolved_end,
        tenant_id=tenant_id,
        user_id=user_id,
        include_staff=include_staff,
    )
