"""TEL-6: the rollups and the seven dashboard queries, on seeded data.

Against a real hypertable and real continuous aggregates, not mocks. Every
number here is one a chart will print, and a query that returns the wrong
number still renders — so an assertion on the value is the only thing that
catches it.

`refresh_continuous_aggregate` is called explicitly after seeding. In
production the hourly policy does that; in a test the policy has not run, and
without the refresh every aggregate-backed assertion would read zero and pass
for the wrong reason.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.settings import get_settings
from app.modules.telemetry.repository import TelemetryRepository, UsageWindow

pytestmark = [pytest.mark.integration]

_INSERT = text(
    """
    INSERT INTO public.usage_events (
        time, id, schema_version, session_id, user_id, tenant_id, actor_role,
        is_platform_staff, event_name, feature, route, farm_id, flow, step,
        outcome, duration_ms, status_code, error_code, correlation_id, locale,
        app_version, device_kind, viewport_w, props
    ) VALUES (
        :time, :id, 1, :session_id, :user_id, :tenant_id, :actor_role,
        :is_platform_staff, :event_name, :feature, :route, NULL, :flow, :step,
        :outcome, :duration_ms, :status_code, :error_code, :correlation_id, 'en',
        'testbuild', 'desktop', 1440, CAST(:props AS jsonb)
    )
    """
)

TODAY = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
WINDOW_START = (TODAY - timedelta(days=7)).date()
WINDOW_END = TODAY.date()


def _row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "time": TODAY - timedelta(hours=1),
        "id": uuid4(),
        "session_id": uuid4(),
        "user_id": uuid4(),
        "tenant_id": None,
        "actor_role": "Agronomist",
        "is_platform_staff": False,
        "event_name": "page_view",
        "feature": None,
        "route": None,
        "flow": None,
        "step": None,
        "outcome": None,
        "duration_ms": None,
        "status_code": None,
        "error_code": None,
        "correlation_id": None,
        "props": "{}",
    }
    base.update(over)
    return base


async def _refresh(session: AsyncSession) -> None:
    """Materialise both aggregates over the seeded range.

    Committed and run outside the test transaction: `refresh_continuous_aggregate`
    is a procedure that cannot run inside a transaction block. Without this the
    aggregate reads empty and every assertion below would pass vacuously.
    """
    await session.commit()
    # A dedicated engine, not `session.get_bind()`. On an AsyncSession that
    # returns a sync-style bind and awaiting IO through it raises
    # MissingGreenlet. `refresh_continuous_aggregate` is also a procedure that
    # cannot run inside a transaction block, so it needs its own autocommit
    # connection either way — which is exactly what the purge engine does.
    start = TODAY - timedelta(days=10)
    end = TODAY + timedelta(days=1)
    engine = create_async_engine(str(get_settings().database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            for view in ("usage_daily", "usage_flow_daily"):
                await conn.execute(
                    text(
                        f"CALL refresh_continuous_aggregate('public.\"{view}\"', CAST(:s AS timestamptz), CAST(:e AS timestamptz))"
                    ),
                    {"s": start, "e": end},
                )
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded(admin_session: AsyncSession) -> AsyncIterator[UUID]:
    """One tenant's week of traffic, plus a platform-staff row to exclude."""
    tenant_id = uuid4()
    staff_tenant = None
    user_a, user_b = uuid4(), uuid4()
    session_a, session_b = uuid4(), uuid4()

    rows: list[dict[str, object]] = [
        # -- two users, two sessions, page views and dwell -------------------
        _row(
            time=TODAY - timedelta(hours=3),
            tenant_id=tenant_id,
            user_id=user_a,
            session_id=session_a,
            event_name="page_view",
            route="/insights/:farmId",
        ),
        _row(
            time=TODAY - timedelta(hours=2),
            tenant_id=tenant_id,
            user_id=user_a,
            session_id=session_a,
            event_name="page_leave",
            route="/insights/:farmId",
            duration_ms=60_000,
        ),
        _row(
            time=TODAY - timedelta(hours=2),
            tenant_id=tenant_id,
            user_id=user_b,
            session_id=session_b,
            event_name="page_view",
            route="/board/:farmId",
        ),
        _row(
            time=TODAY - timedelta(hours=1),
            tenant_id=tenant_id,
            user_id=user_b,
            session_id=session_b,
            event_name="page_leave",
            route="/board/:farmId",
            duration_ms=10_000,
        ),
        # -- capability use ---------------------------------------------------
        _row(
            time=TODAY - timedelta(hours=2),
            tenant_id=tenant_id,
            user_id=user_a,
            session_id=session_a,
            event_name="feature_used",
            feature="insights",
            duration_ms=500,
            props='{"action": "open"}',
        ),
        # -- a funnel: entered twice, completed once --------------------------
        _row(
            time=TODAY - timedelta(hours=5),
            tenant_id=tenant_id,
            user_id=user_a,
            session_id=session_a,
            event_name="flow_start",
            flow="farm_onboarding",
        ),
        _row(
            time=TODAY - timedelta(hours=4),
            tenant_id=tenant_id,
            user_id=user_a,
            session_id=session_a,
            event_name="flow_step",
            flow="farm_onboarding",
            step="details",
        ),
        _row(
            time=TODAY - timedelta(hours=3),
            tenant_id=tenant_id,
            user_id=user_a,
            session_id=session_a,
            event_name="flow_complete",
            flow="farm_onboarding",
            outcome="ok",
        ),
        _row(
            time=TODAY - timedelta(hours=5),
            tenant_id=tenant_id,
            user_id=user_b,
            session_id=session_b,
            event_name="flow_start",
            flow="farm_onboarding",
        ),
        _row(
            time=TODAY - timedelta(hours=4),
            tenant_id=tenant_id,
            user_id=user_b,
            session_id=session_b,
            event_name="flow_step",
            flow="farm_onboarding",
            step="subscriptions",
        ),
        # -- a failure, with a correlation id ---------------------------------
        _row(
            time=TODAY - timedelta(hours=1),
            tenant_id=tenant_id,
            user_id=user_b,
            session_id=session_b,
            event_name="api_error",
            route="/board/:farmId",
            outcome="error",
            status_code=500,
            error_code="http_500",
            correlation_id=uuid4(),
            props='{"method": "GET"}',
        ),
        # -- platform staff: must not appear in any default result ------------
        _row(
            time=TODAY - timedelta(hours=1),
            tenant_id=staff_tenant,
            event_name="page_view",
            route="/platform/usage",
            is_platform_staff=True,
            actor_role="PlatformAdmin",
        ),
    ]
    # 25 page views on one route so error_dense_routes clears its min_views
    # floor. Below the floor the route is correctly hidden as noise, which
    # would make the struggle assertion pass for the wrong reason.
    rows.extend(
        _row(
            time=TODAY - timedelta(hours=1, minutes=i),
            tenant_id=tenant_id,
            user_id=user_b,
            session_id=session_b,
            event_name="page_view",
            route="/board/:farmId",
        )
        for i in range(25)
    )

    await admin_session.execute(_INSERT, rows)
    await _refresh(admin_session)
    yield tenant_id
    engine = create_async_engine(str(get_settings().database_url), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text("DELETE FROM public.usage_events WHERE app_version = 'testbuild'")
            )
    finally:
        await engine.dispose()


def _window(tenant_id: UUID | None, **over: object) -> UsageWindow:
    return UsageWindow(
        start=WINDOW_START,
        end=WINDOW_END,
        tenant_id=tenant_id,
        **over,  # type: ignore[arg-type]
    )


# --- engagement -------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_users_counts_distinct_people(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    """Acceptance question 1: how many distinct users used it last week."""
    repo = TelemetryRepository(admin_session)
    actives = await repo.active_users(_window(seeded))
    assert actives["dau"] == 2
    assert actives["wau"] == 2
    assert actives["mau"] == 2


@pytest.mark.asyncio
async def test_platform_staff_are_excluded_by_default(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    """Acceptance criterion 9. The staff row has no tenant_id, so this is
    asked without a tenant filter — otherwise the tenant clause would exclude
    it and the test would prove nothing about the staff flag."""
    repo = TelemetryRepository(admin_session)
    routes = {r["route"] for r in await repo.time_by_route(_window(None))}
    assert "/platform/usage" not in routes

    with_staff = await repo.daily_activity(_window(None, include_staff=True))
    without_staff = await repo.daily_activity(_window(None))
    assert sum(p["events"] for p in with_staff) > sum(p["events"] for p in without_staff)


@pytest.mark.asyncio
async def test_time_by_route_ranks_by_visible_dwell(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    """Acceptance question 2: which surfaces absorb the most user time."""
    repo = TelemetryRepository(admin_session)
    routes = await repo.time_by_route(_window(seeded))
    assert routes, "no dwell rows — did the aggregate refresh run?"
    assert routes[0]["route"] == "/insights/:farmId"
    assert routes[0]["total_ms"] == 60_000
    assert routes[0]["median_ms"] == 60_000


@pytest.mark.asyncio
async def test_session_stats_derives_length_from_first_and_last_event(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    repo = TelemetryRepository(admin_session)
    stats = await repo.session_stats(_window(seeded))
    assert stats["sessions"] == 2
    # Session A spans 5 h to 1 h before now; session B spans 5 h to ~1 h.
    assert stats["median_session_seconds"] > 3600
    assert stats["sessions_per_user"] == 1.0


# --- adoption ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_feature_adoption_reports_reach_not_just_volume(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    repo = TelemetryRepository(admin_session)
    rows = {r["feature"]: r for r in await repo.feature_adoption(_window(seeded))}
    assert rows["insights"]["events"] == 1
    assert rows["insights"]["users"] == 1
    assert rows["insights"]["tenants"] == 1


@pytest.mark.asyncio
async def test_cold_features_names_capabilities_with_no_rows_at_all(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    """Acceptance question 3, and the one query that cannot come from the data:
    a capability nobody ever used produces no rows to find."""
    repo = TelemetryRepository(admin_session)
    cold = await repo.cold_features(["insights", "reports", "board"], _window(seeded))
    assert cold == ["board", "reports"]


# --- funnels ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_funnel_derives_abandonment(admin_session: AsyncSession, seeded: UUID) -> None:
    """Acceptance question 4: what fraction complete, and which step kills the
    rest. The abandoning session sent no abandon event — it never could."""
    repo = TelemetryRepository(admin_session)
    funnels = {f["flow"]: f for f in await repo.flow_funnel(_window(seeded))}
    onboarding = funnels["farm_onboarding"]
    assert onboarding["entries"] == 2
    assert onboarding["completions"] == 1
    assert onboarding["abandoned"] == 1
    assert onboarding["died_at"] == "subscriptions"


@pytest.mark.asyncio
async def test_flow_steps_counts_distinct_sessions(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    repo = TelemetryRepository(admin_session)
    steps = {(s["flow"], s["step"]): s["sessions"] for s in await repo.flow_steps(_window(seeded))}
    assert steps[("farm_onboarding", "details")] == 1
    assert steps[("farm_onboarding", "subscriptions")] == 1


# --- struggle ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_dense_routes_and_correlation_id(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    """Acceptance question 5: the worst route, and a correlation_id that
    reaches the server log line for a real failure there."""
    repo = TelemetryRepository(admin_session)
    dense = await repo.error_dense_routes(_window(seeded))
    assert dense, "expected /board/:farmId over the min_views floor"
    assert dense[0]["route"] == "/board/:farmId"
    assert dense[0]["errors"] == 1
    assert dense[0]["views"] == 26

    recent = await repo.recent_errors(_window(seeded), route="/board/:farmId")
    assert len(recent) == 1
    assert recent[0]["correlation_id"] is not None
    assert recent[0]["status_code"] == 500
    assert recent[0]["method"] == "GET"


@pytest.mark.asyncio
async def test_error_dense_routes_hides_low_traffic_noise(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    """A route with 2 views and 1 error is 50% and means nothing. Without the
    floor the struggle board is permanently topped by noise."""
    repo = TelemetryRepository(admin_session)
    dense = await repo.error_dense_routes(_window(seeded), min_views=1000)
    assert dense == []


# --- tenant health ----------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_health_reports_breadth_and_last_seen(
    admin_session: AsyncSession, seeded: UUID
) -> None:
    repo = TelemetryRepository(admin_session)
    rows = {r["tenant_id"]: r for r in await repo.tenant_health(_window(seeded))}
    assert seeded in rows
    assert rows[seeded]["last_seen"] == date.today()
    assert rows[seeded]["wau"] == 2
    assert rows[seeded]["features_used"] == 1
