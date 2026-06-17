"""Integration: `derive_weather_daily` materialises `weather_index_daily`.

Exercises the PR-W2 projection wired into the derivation task body —
seeds hourly observations (incl. radiation + wind), runs fetch + derive,
and asserts the 7 catalog indices land with a NULL z-score (no
climatology baselines exist until PR-W3).
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
from app.modules.weather.providers.protocol import FetchResult, HourlyObservation
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
