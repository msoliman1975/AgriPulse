"""Integration: `derive_weather_daily` materialises `weather_index_daily`.

Exercises the PR-W2 projection wired into the derivation task body —
seeds hourly observations (incl. radiation + wind), runs fetch + derive,
and asserts the 7 catalog indices land with a NULL z-score (no
climatology baselines exist until PR-W3).

The second half of the file covers the forward projection (migration
0072): the same task also reads `weather_forecasts` and writes the days
past today as `is_forecast` index rows, which is what lets the overview's
weather charts continue past the current date.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.modules.weather import tasks as weather_tasks
from app.modules.weather.providers.protocol import (
    FetchResult,
    HourlyForecast,
    HourlyObservation,
)
from app.shared.auth.context import TenantRole

from .conftest import (
    ASGITransport,
    AsyncClient,
    build_app,
    create_farm_and_block,
    create_user_in_tenant,
    make_context,
)

pytestmark = [pytest.mark.integration]


class _FakeProvider:
    code = "open_meteo"

    def __init__(self, result: FetchResult) -> None:
        self._result = result

    async def fetch(self, **_: Any) -> FetchResult:
        return self._result

    async def aclose(self) -> None:
        pass


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, str]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"WX idx {slug}", contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await create_farm_and_block(client)
        sub = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        assert sub.status_code == 201, sub.text
    return tenant, farm_id


def _obs(iso_utc: str, hour_of_day: int) -> HourlyObservation:
    # Daytime radiation only; constant wind from due south; mild humidity.
    daytime = 6 <= hour_of_day <= 18
    return HourlyObservation(
        time=datetime.fromisoformat(iso_utc).replace(tzinfo=UTC),
        air_temp_c=Decimal("24.0"),
        humidity_pct=Decimal("55"),
        precipitation_mm=Decimal("0.5"),
        wind_speed_m_s=Decimal("3.0"),
        wind_direction_deg=Decimal("180"),
        solar_radiation_w_m2=Decimal("500") if daytime else Decimal("0"),
        et0_mm=Decimal("0.2"),
    )


def _fc(at: datetime) -> HourlyForecast:
    """One forecast hour. Deliberately unlike `_obs` — warmer, wetter, no
    wind direction (the forecast table has no such column) — so a value
    that came from the forecast half is recognisable on sight."""
    daytime = 6 <= at.hour <= 18
    return HourlyForecast(
        time=at,
        air_temp_c=Decimal("30.0"),
        humidity_pct=Decimal("70"),
        precipitation_mm=Decimal("1.0"),
        precipitation_probability_pct=Decimal("60"),
        wind_speed_m_s=Decimal("4.0"),
        solar_radiation_w_m2=Decimal("600") if daytime else Decimal("0"),
        et0_mm=Decimal("0.3"),
    )


async def _run_cycle(
    tenant_schema: str,
    farm_id: str,
    *,
    obs_hours: int = 48,
    forecast_hours: int = 0,
) -> None:
    """One fetch + derive cycle with a fake provider.

    `forecast_hours` counts forward from the top of the current hour, so
    120 gives the provider's real 5-day horizon.
    """
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _obs((now - timedelta(hours=h)).isoformat(), (now - timedelta(hours=h)).hour)
        for h in range(obs_hours)
    )
    forecasts = tuple(_fc(now + timedelta(hours=h)) for h in range(1, forecast_hours + 1))
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=forecasts)
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant_schema, "open_meteo")
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant_schema)
    finally:
        weather_tasks.reset_provider_factory()


async def _index_rows(admin_session: AsyncSession, schema: str, farm_id: str) -> list[Any]:
    return list(
        (
            await admin_session.execute(
                text(
                    f"SELECT date, index_code, value, is_forecast "
                    f'FROM "{schema}".weather_index_daily '
                    f"WHERE farm_id = :fid ORDER BY date, index_code"
                ),
                {"fid": UUID(farm_id)},
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_derive_writes_weather_index_rows(admin_session: AsyncSession) -> None:
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-writes")

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _obs((now - timedelta(hours=h)).isoformat(), (now - timedelta(hours=h)).hour)
        for h in range(48)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
    finally:
        weather_tasks.reset_provider_factory()

    rows = (
        await admin_session.execute(
            text(
                f"SELECT date, index_code, value, value_min, value_max, value_aux, "
                f"baseline_deviation "
                f'FROM "{tenant.schema_name}".weather_index_daily '
                f"WHERE farm_id = :fid ORDER BY date, index_code"
            ),
            {"fid": UUID(farm_id)},
        )
    ).all()
    assert rows, "expected weather_index_daily rows"

    codes = {r.index_code for r in rows}
    # Every catalog index that has source data should be present.
    assert {
        "temperature",
        "radiation",
        "wind",
        "rainfall",
        "evapotranspiration",
        "evaporation_coeff",
        "rain_et_balance",
    } <= codes

    by_code = {r.index_code: r for r in rows if r.date == max(x.date for x in rows)}
    # Temperature: mean headline + min/max spread.
    assert by_code["temperature"].value == Decimal("24.000")
    assert by_code["temperature"].value_min is not None
    # Wind carries its vector-mean direction (due south).
    assert by_code["wind"].value_aux.get("mean_direction_deg") == "180.0"
    # rain_et_balance flux = precip - et0; with 0.5 - 0.2 per hour summed
    # over a day it stays positive-ish but is non-null.
    assert by_code["rain_et_balance"].value is not None
    # No climatology baselines yet → z-score is NULL.
    for r in rows:
        assert r.baseline_deviation is None


@pytest.mark.asyncio
async def test_derive_index_rows_idempotent(admin_session: AsyncSession) -> None:
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-idemp")
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _obs((now - timedelta(hours=h)).isoformat(), (now - timedelta(hours=h)).hour)
        for h in range(48)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))

    async def _count() -> int:
        return (
            await admin_session.execute(
                text(
                    f'SELECT count(*) FROM "{tenant.schema_name}".weather_index_daily '
                    f"WHERE farm_id = :fid"
                ),
                {"fid": UUID(farm_id)},
            )
        ).scalar_one()

    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
        first = await _count()
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
        second = await _count()
    finally:
        weather_tasks.reset_provider_factory()
    assert first > 0
    assert first == second


# --- Forward projection (migration 0072) -----------------------------------


@pytest.mark.asyncio
async def test_derive_projects_the_forecast_horizon(admin_session: AsyncSession) -> None:
    """The reason this exists: the series must continue past today.

    Before 0072 the task read only `weather_observations` and capped its
    targets at today, so every weather index stopped dead at the current
    date even though 5 days of forecast sat in `weather_forecasts`.
    """
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-fc")
    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=120)

    rows = await _index_rows(admin_session, tenant.schema_name, farm_id)
    observed = [r for r in rows if not r.is_forecast]
    forecast = [r for r in rows if r.is_forecast]

    assert observed, "expected observed index rows"
    assert forecast, "expected the forecast horizon to be projected"

    # The forward half starts strictly after the observed half ends. Asserted
    # against the data rather than against "today" so the test does not have
    # to reconstruct the farm's local date.
    assert min(r.date for r in forecast) > max(r.date for r in observed)

    # 120 hours from mid-day yields 4 whole local days plus a stub that the
    # coverage floor drops; the exact count depends on the hour the suite
    # runs at, so assert the floor rather than an exact number.
    assert len({r.date for r in forecast}) >= 4

    # Every index the catalog defines is projected forward, not just the
    # temperature-shaped ones — the reported gap named humidity and the
    # rain/ET balance specifically.
    assert {
        "temperature",
        "radiation",
        "wind",
        "humidity",
        "rainfall",
        "evapotranspiration",
        "evaporation_coeff",
        "rain_et_balance",
    } <= {r.index_code for r in forecast}


@pytest.mark.asyncio
async def test_forecast_days_stay_out_of_derived_daily(admin_session: AsyncSession) -> None:
    """`weather_derived_daily` remains a record of observed weather.

    The reports module builds its weather table on that spine and LEFT JOINs
    index rows onto it, so a predicted row there would put forecast GDD and
    season totals into a report of what happened.
    """
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-fc-derived")
    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=120)

    rows = await _index_rows(admin_session, tenant.schema_name, farm_id)
    forecast_dates = {r.date for r in rows if r.is_forecast}
    assert forecast_dates

    leaked = (
        await admin_session.execute(
            text(
                f'SELECT date FROM "{tenant.schema_name}".weather_derived_daily '
                f"WHERE farm_id = :fid AND date = ANY(:dates)"
            ),
            {"fid": UUID(farm_id), "dates": list(forecast_dates)},
        )
    ).all()
    assert leaked == []


@pytest.mark.asyncio
async def test_stale_forecast_days_are_retracted(admin_session: AsyncSession) -> None:
    """The stored forecast half is exactly what the last run computed.

    Note this cannot be provoked by handing the provider a shorter horizon:
    `weather_forecasts` keeps every issuance, so `read_latest_forecast`
    still returns the wider window written earlier and the projection still
    covers the same days. The orphan case is a forecast index row for a day
    the current projection does not reach at all — a raised coverage floor,
    a retention sweep over the hypertable — so that is what is staged here.
    """
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-fc-stale")
    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=120)

    live = {
        r.date
        for r in await _index_rows(admin_session, tenant.schema_name, farm_id)
        if r.is_forecast
    }
    assert len(live) >= 4

    # A leftover from an earlier, wider projection: 30 days out, far beyond
    # any horizon the provider offers.
    orphan = max(live) + timedelta(days=25)
    await admin_session.execute(
        text(
            f'INSERT INTO "{tenant.schema_name}".weather_index_daily '
            f"(farm_id, date, index_code, value, value_aux, is_forecast) "
            f"VALUES (:fid, :d, 'temperature', 21.0, '{{}}'::jsonb, TRUE)"
        ),
        {"fid": UUID(farm_id), "d": orphan},
    )
    await admin_session.commit()

    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=120)

    rows = await _index_rows(admin_session, tenant.schema_name, farm_id)
    assert orphan not in {r.date for r in rows}, "stale forecast day should be retracted"
    # The days the projection does reach survive, and so does all observed
    # history — `is_forecast` is the only thing that delete keys on.
    assert {r.date for r in rows if r.is_forecast} == live
    assert [r for r in rows if not r.is_forecast]


@pytest.mark.asyncio
async def test_partial_trailing_day_is_not_projected(admin_session: AsyncSession) -> None:
    """A few hours at the end of the horizon is not a day.

    Projecting it would post a daily rainfall total of "3 hours' worth" and
    an ET total to match, which reads as a genuine dry day rather than as
    missing data. A whole absent day is the honest failure.
    """
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-fc-partial")
    # Just past midnight-plus-a-bit of coverage: never a full local day.
    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=6)

    rows = await _index_rows(admin_session, tenant.schema_name, farm_id)
    assert [r for r in rows if not r.is_forecast], "observed half should still land"
    assert [r for r in rows if r.is_forecast] == []


@pytest.mark.asyncio
async def test_forecast_row_flips_to_observed_when_the_day_arrives(
    admin_session: AsyncSession,
) -> None:
    """The handover is a plain upsert on the same key.

    Simulated by writing a forecast row for today directly — the projection
    itself never targets today as forecast — and then running the observed
    derivation over it. Nothing should be left flagged.
    """
    tenant, farm_id = await _bootstrap(admin_session, "wx-idx-fc-handover")
    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=120)

    today = (
        await admin_session.execute(
            text(
                f'SELECT max(date) FROM "{tenant.schema_name}".weather_index_daily '
                f"WHERE farm_id = :fid AND NOT is_forecast"
            ),
            {"fid": UUID(farm_id)},
        )
    ).scalar_one()
    await admin_session.execute(
        text(
            f'UPDATE "{tenant.schema_name}".weather_index_daily '
            f"SET is_forecast = TRUE WHERE farm_id = :fid AND date = :d"
        ),
        {"fid": UUID(farm_id), "d": today},
    )
    await admin_session.commit()

    await _run_cycle(tenant.schema_name, farm_id, forecast_hours=120)

    still_flagged = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{tenant.schema_name}".weather_index_daily '
                f"WHERE farm_id = :fid AND date = :d AND is_forecast"
            ),
            {"fid": UUID(farm_id), "d": today},
        )
    ).scalar_one()
    assert still_flagged == 0
