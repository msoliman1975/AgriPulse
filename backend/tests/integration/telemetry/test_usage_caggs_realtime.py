"""The aggregates must show data that has NOT been materialised yet.

This is the test that was missing. `test_usage_queries.py` calls
`refresh_continuous_aggregate` explicitly before asserting, which guarantees
materialised buckets — so every assertion in it passed against a view
configured in a way production would never hit, and the dashboard shipped
empty.

The failure it missed: 0083 assumed `timescaledb.materialized_only` defaults to
false. That default flipped in TimescaleDB 2.13, so both views shipped with
real-time aggregation off and returned only materialised buckets. 74 raw events
in production, zero rows out of `usage_daily`.

So this file deliberately does NOT refresh. Inserting a row and reading it back
through the aggregate is the whole point, and it is the only assertion that
distinguishes a working dashboard from an empty one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration]

_INSERT = text(
    """
    INSERT INTO public.usage_events (
        time, id, schema_version, session_id, user_id, tenant_id, actor_role,
        is_platform_staff, event_name, feature, route, outcome, duration_ms,
        locale, app_version, props
    ) VALUES (
        :time, :id, 1, :session_id, :user_id, :tenant_id, 'Agronomist',
        false, 'page_view', 'insights', :route, 'ok', 1000,
        'en', 'realtimetest', '{}'::jsonb
    )
    """
)


@pytest.fixture
async def fresh_event(admin_session: AsyncSession) -> AsyncIterator[UUID]:
    tenant_id = uuid4()
    await admin_session.execute(
        _INSERT,
        {
            "time": datetime.now(UTC) - timedelta(minutes=1),
            "id": uuid4(),
            "session_id": uuid4(),
            "user_id": uuid4(),
            "tenant_id": tenant_id,
            "route": "/insights/:farmId",
        },
    )
    await admin_session.commit()
    yield tenant_id
    await admin_session.execute(
        text("DELETE FROM public.usage_events WHERE app_version = 'realtimetest'")
    )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_both_aggregates_have_real_time_aggregation_on(
    admin_session: AsyncSession,
) -> None:
    """Assert the flag directly, so the reason is obvious when it regresses.

    A future TimescaleDB upgrade can move this default again; the point of
    naming it here is that the next person gets "materialized_only is true"
    rather than "the dashboard is empty".
    """
    rows = dict(
        (
            await admin_session.execute(
                text(
                    "SELECT view_name, materialized_only "
                    "FROM timescaledb_information.continuous_aggregates "
                    "WHERE view_schema = 'public' AND view_name LIKE 'usage%'"
                )
            )
        ).all()
    )
    assert rows, "neither usage aggregate exists"
    assert rows == dict.fromkeys(rows, False), (
        f"real-time aggregation is off: {rows}. The dashboard reads these views, "
        "so anything newer than the last refresh is invisible — which is how "
        "Phase A shipped with 74 raw events and an empty page."
    )


@pytest.mark.asyncio
async def test_a_brand_new_event_is_visible_without_a_refresh(
    admin_session: AsyncSession, fresh_event: UUID
) -> None:
    """No `refresh_continuous_aggregate` call anywhere in this test. That is the
    point: the dashboard does not get to run one either."""
    events = (
        await admin_session.execute(
            text("SELECT sum(events) FROM public.usage_daily WHERE tenant_id = :t"),
            {"t": fresh_event},
        )
    ).scalar_one_or_none()
    assert events == 1, (
        "an event written a minute ago is not visible through usage_daily. The "
        "refresh policy runs hourly with a one-hour end_offset, so without "
        "real-time aggregation the dashboard is always at least an hour blind."
    )
