"""`weather.reap_stale_attempts` closes attempts a dead worker left open.

A weather attempt row is a log entry, not a queue entry: the next poll is
driven by the subscription's `last_attempted_at`, so an orphan blocks
nothing. It does pin the Integration Health page, which counts
`status = 'running'` with no age limit at all.

Production, 2026-08-25. Tenant agrosina carried 36 attempts still `running`
from 2026-08-13 04:07 — one per block of a farm that had just cut over to
the farm-level weather path — and the page read "36 running" for farm
Bashier Elkhier, whose weather had in fact synced at 04:33 that morning.
Imagery got a reaper for the same shape of row in #561; weather never did.

Unlike the imagery reaper this re-runs nothing. One provider call covers the
whole farm on a cadence, so the next scheduled poll already writes whatever
the dead attempt would have.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.modules.weather.repository import WeatherRepository

pytestmark = [pytest.mark.integration]

_FARM = "POLYGON((31.20 30.00,31.21 30.00,31.21 30.01,31.20 30.01,31.20 30.00))"


async def _attempt(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: UUID,
    sub_id: UUID,
    status: str,
    started_hours_ago: float,
) -> UUID:
    attempt_id = uuid4()
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO weather_ingestion_attempts "
            "(id, subscription_id, block_id, farm_id, provider_code, started_at, status) "
            "VALUES (:id, :sub, NULL, :fid, 'open_meteo', :started, :st)"
        ),
        {
            "id": str(attempt_id),
            "sub": str(sub_id),
            "fid": str(farm_id),
            "started": datetime.now(UTC) - timedelta(hours=started_hours_ago),
            "st": status,
        },
    )
    await session.execute(text("SET search_path TO public"))
    await session.commit()
    return attempt_id


async def _status(session: AsyncSession, schema: str, attempt_id: UUID) -> tuple[str, str | None]:
    row = (
        await session.execute(
            text(
                f'SELECT status, error_code FROM "{schema}".weather_ingestion_attempts '
                "WHERE id = :id"
            ),
            {"id": str(attempt_id)},
        )
    ).one()
    return str(row[0]), row[1]


@pytest.mark.asyncio
async def test_reaper_closes_old_running_and_leaves_fresh_ones(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-reap",
        name="Weather Reap",
        contact_email="ops@weather-reap.test",
    )
    schema = tenant.schema_name
    farm_id, sub_id = uuid4(), uuid4()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'RE', 'Reap farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": _FARM},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    stale = await _attempt(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        sub_id=sub_id,
        status="running",
        started_hours_ago=288,
    )
    fresh = await _attempt(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        sub_id=sub_id,
        status="running",
        started_hours_ago=0.1,
    )
    done = await _attempt(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        sub_id=sub_id,
        status="succeeded",
        started_hours_ago=400,
    )

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    closed = await WeatherRepository(admin_session).close_stale_running_attempts(stale_hours=6)
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    assert closed == 1
    assert await _status(admin_session, schema, stale) == ("failed", "reaped_stale")
    assert (await _status(admin_session, schema, fresh))[0] == "running"
    assert (await _status(admin_session, schema, done))[0] == "succeeded"


@pytest.mark.asyncio
async def test_a_reaped_attempt_does_not_count_as_a_recent_failure(
    admin_session: AsyncSession,
) -> None:
    """A 12-day-old row closed today must not raise a 24h failure count.

    `v_farm_integration_health.weather_failed_24h` filters on `started_at`,
    not on `completed_at`, so a reaped row falls outside the window. Assert
    it, because closing 36 rows at once on a live tenant would otherwise
    read as a sudden outage.
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-reap-window",
        name="Weather Reap Window",
        contact_email="ops@weather-reap-window.test",
    )
    schema = tenant.schema_name
    farm_id, sub_id = uuid4(), uuid4()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, 'RW', 'Reap window farm', ST_GeomFromText(:wkt, 4326))"
        ),
        {"id": str(farm_id), "wkt": _FARM},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    await _attempt(
        admin_session,
        schema=schema,
        farm_id=farm_id,
        sub_id=sub_id,
        status="running",
        started_hours_ago=288,
    )
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await WeatherRepository(admin_session).close_stale_running_attempts(stale_hours=6)
    await admin_session.commit()

    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    row = (
        await admin_session.execute(
            text(
                "SELECT weather_failed_24h, weather_running_count "
                "FROM v_farm_integration_health WHERE farm_id = :id"
            ),
            {"id": str(farm_id)},
        )
    ).one()
    await admin_session.execute(text("SET search_path TO public"))
    assert int(row[0]) == 0
    assert int(row[1]) == 0
