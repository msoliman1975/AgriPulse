"""End-to-end tests for the PR-C read endpoints.

  GET /blocks/{id}/weather/forecast       — daily aggregation in farm tz
  GET /blocks/{id}/weather/observations   — hourly window
  GET /blocks/{id}/weather/derived        — derived daily window

Plus the `derive_weather_daily` Celery task body, exercised directly to
confirm the chain from `fetch_weather` lands real rows in
`weather_derived_daily`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Stub WeatherProvider returning a pre-built FetchResult."""

    code = "open_meteo"

    def __init__(self, result: FetchResult) -> None:
        self._result = result

    async def fetch(self, **_: Any) -> FetchResult:
        return self._result

    async def aclose(self) -> None:
        pass


def _hourly_obs(
    iso_utc: str,
    temp: float,
    precip: float = 0.0,
    et0: float = 0.0,
) -> HourlyObservation:
    return HourlyObservation(
        time=datetime.fromisoformat(iso_utc).replace(tzinfo=UTC),
        air_temp_c=Decimal(str(temp)),
        precipitation_mm=Decimal(str(precip)),
        et0_mm=Decimal(str(et0)),
    )


def _hourly_fc(
    iso_utc: str,
    temp: float,
    precip: float = 0.0,
    precip_prob: float | None = None,
) -> HourlyForecast:
    return HourlyForecast(
        time=datetime.fromisoformat(iso_utc).replace(tzinfo=UTC),
        air_temp_c=Decimal(str(temp)),
        precipitation_mm=Decimal(str(precip)),
        precipitation_probability_pct=(
            Decimal(str(precip_prob)) if precip_prob is not None else None
        ),
    )


async def _bootstrap_tenant_with_block(
    admin_session: AsyncSession, slug: str
) -> tuple[Any, str, str]:
    """Create tenant + admin user + farm + block. Returns (tenant, farm_id, block_id)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"Weather PR-C {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, block_id = await create_farm_and_block(client)
        # Subscribe so derive_weather_daily has rows to work with.
        sub = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        assert sub.status_code == 201, sub.text
    return tenant, farm_id, block_id


# ---------------------------------------------------------------------------
# derive_weather_daily — task body writes real rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derive_weather_daily_writes_rows(admin_session: AsyncSession) -> None:
    """After fetch + derive, weather_derived_daily has rows for today + yesterday."""
    tenant, farm_id, _block_id = await _bootstrap_tenant_with_block(
        admin_session, "wx-derive-writes"
    )

    # Three days of synthetic past observations covering yesterday and today
    # in UTC. Real Open-Meteo returns 48h, this is enough to populate
    # both target days.
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _hourly_obs(
            (now - timedelta(hours=h)).isoformat(),
            temp=20.0 + (h % 5),
            precip=0.5,
            et0=0.1,
        )
        for h in range(48)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
    finally:
        weather_tasks.reset_provider_factory()

    # At least today's row should be present (yesterday too, depending on
    # how many UTC hours fall on each local day).
    rows = (
        await admin_session.execute(
            text(
                f"SELECT date, temp_mean_c, precip_mm_daily, et0_mm_daily, gdd_base10, "
                f"gdd_cumulative_base10_season, precip_mm_7d "
                f'FROM "{tenant.schema_name}".weather_derived_daily '
                f"WHERE farm_id = :fid ORDER BY date"
            ),
            {"fid": UUID(farm_id)},
        )
    ).all()
    assert len(rows) >= 1, "expected derive_weather_daily to write at least one row"
    # All non-null aggregates make sense.
    for row in rows:
        assert row.temp_mean_c is not None
        assert row.precip_mm_daily is not None
        assert row.precip_mm_daily >= Decimal("0")
        assert row.et0_mm_daily is not None
        assert row.et0_mm_daily >= Decimal("0")
        assert row.gdd_base10 is not None
        assert row.gdd_base10 >= Decimal("0")
        # Cumulative is at least the day's own contribution.
        assert row.gdd_cumulative_base10_season is not None
        # Rolling 7d includes today's precip, so it's >= today's precip.
        assert row.precip_mm_7d is not None


@pytest.mark.asyncio
async def test_derive_weather_daily_idempotent(admin_session: AsyncSession) -> None:
    """Running the task twice doesn't duplicate rows; ON CONFLICT DO UPDATE."""
    tenant, farm_id, _block_id = await _bootstrap_tenant_with_block(
        admin_session, "wx-derive-idemp"
    )
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(_hourly_obs((now - timedelta(hours=h)).isoformat(), temp=22.0) for h in range(48))
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
        first_count = (
            await admin_session.execute(
                text(
                    f'SELECT count(*) FROM "{tenant.schema_name}".weather_derived_daily '
                    f"WHERE farm_id = :fid"
                ),
                {"fid": UUID(farm_id)},
            )
        ).scalar_one()
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
        second_count = (
            await admin_session.execute(
                text(
                    f'SELECT count(*) FROM "{tenant.schema_name}".weather_derived_daily '
                    f"WHERE farm_id = :fid"
                ),
                {"fid": UUID(farm_id)},
            )
        ).scalar_one()
    finally:
        weather_tasks.reset_provider_factory()
    assert first_count == second_count


# ---------------------------------------------------------------------------
# GET /weather/forecast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forecast_endpoint_aggregates_in_farm_tz(admin_session: AsyncSession) -> None:
    """Forecast endpoint returns one row per local-tz day with high/low/precip."""
    tenant, farm_id, block_id = await _bootstrap_tenant_with_block(admin_session, "wx-forecast-tz")

    # Build hourly forecasts spanning today + tomorrow Cairo time.
    cairo_offset = timedelta(hours=2)
    today_local_midnight_utc = (
        datetime.now(UTC).replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    )
    # Anchor on Cairo "today 00:00".
    now_cairo = datetime.now(UTC) + cairo_offset
    today_local_midnight_cairo = now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
    today_midnight_utc = today_local_midnight_cairo.astimezone(UTC).replace(tzinfo=UTC)
    del today_local_midnight_utc  # silence unused — kept for readability

    # Two hours today (cairo), high 30 / low 25, with one rainy hour
    # (probability 80%, precip 5mm). Tomorrow has nothing — that day's
    # bucket should come back all-None but still present.
    fcs = (
        HourlyForecast(
            time=today_midnight_utc + timedelta(hours=10),  # 10:00 Cairo today
            air_temp_c=Decimal("30.0"),
            precipitation_mm=Decimal("0.0"),
            precipitation_probability_pct=Decimal("10.0"),
        ),
        HourlyForecast(
            time=today_midnight_utc + timedelta(hours=14),  # 14:00 Cairo today
            air_temp_c=Decimal("25.0"),
            precipitation_mm=Decimal("5.0"),
            precipitation_probability_pct=Decimal("80.0"),
        ),
    )
    result = FetchResult(forecast_issued_at=today_midnight_utc, observations=(), forecasts=fcs)
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
    finally:
        weather_tasks.reset_provider_factory()

    # Hit the read endpoint as TenantAdmin.
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/blocks/{block_id}/weather/forecast?horizon_days=2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "Africa/Cairo"
    assert len(body["days"]) == 2
    today_bucket = body["days"][0]
    assert Decimal(today_bucket["high_c"]) == Decimal("30.0")
    assert Decimal(today_bucket["low_c"]) == Decimal("25.0")
    assert Decimal(today_bucket["precip_mm_total"]) == Decimal("5.00")
    assert Decimal(today_bucket["precip_probability_max_pct"]) == Decimal("80.0")
    # Tomorrow has no data — the row exists but values are all None.
    tomorrow_bucket = body["days"][1]
    assert tomorrow_bucket["high_c"] is None
    assert tomorrow_bucket["precip_mm_total"] is None


@pytest.mark.asyncio
async def test_forecast_returns_only_latest_issuance(admin_session: AsyncSession) -> None:
    """Two issuances for the same hour → endpoint returns the newer one."""
    tenant, farm_id, block_id = await _bootstrap_tenant_with_block(
        admin_session, "wx-forecast-latest"
    )

    now_cairo = datetime.now(UTC) + timedelta(hours=2)
    today_midnight_cairo = now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
    today_midnight_utc = today_midnight_cairo.astimezone(UTC).replace(tzinfo=UTC)
    target_time = today_midnight_utc + timedelta(hours=12)

    issuance_a = today_midnight_utc
    issuance_b = today_midnight_utc + timedelta(hours=1)  # newer

    old_fc = HourlyForecast(time=target_time, air_temp_c=Decimal("20.0"))
    new_fc = HourlyForecast(time=target_time, air_temp_c=Decimal("28.0"))

    weather_tasks.set_provider_factory(
        lambda _code: _FakeProvider(
            FetchResult(forecast_issued_at=issuance_a, observations=(), forecasts=(old_fc,))
        )
    )
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
    finally:
        weather_tasks.reset_provider_factory()

    weather_tasks.set_provider_factory(
        lambda _code: _FakeProvider(
            FetchResult(forecast_issued_at=issuance_b, observations=(), forecasts=(new_fc,))
        )
    )
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
    finally:
        weather_tasks.reset_provider_factory()

    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    ctx = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/blocks/{block_id}/weather/forecast?horizon_days=1")
    body = resp.json()
    # high_c = 28 means we picked the newer issuance, not the 20 from the older one.
    assert Decimal(body["days"][0]["high_c"]) == Decimal("28.0")


# ---------------------------------------------------------------------------
# GET /weather/observations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observations_endpoint_returns_window(admin_session: AsyncSession) -> None:
    tenant, farm_id, block_id = await _bootstrap_tenant_with_block(admin_session, "wx-obs-window")

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _hourly_obs((now - timedelta(hours=h)).isoformat(), temp=22.0 + h) for h in range(5)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
    finally:
        weather_tasks.reset_provider_factory()

    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    ctx = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        since = (now - timedelta(hours=10)).isoformat()
        until = (now + timedelta(hours=1)).isoformat()
        resp = await client.get(
            f"/api/v1/blocks/{block_id}/weather/observations",
            params={"since": since, "until": until},
        )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 5
    # Ascending by time.
    times = [r["time"] for r in rows]
    assert times == sorted(times)


# ---------------------------------------------------------------------------
# GET /weather/derived
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derived_endpoint_returns_window(admin_session: AsyncSession) -> None:
    tenant, farm_id, block_id = await _bootstrap_tenant_with_block(
        admin_session, "wx-derived-window"
    )

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _hourly_obs((now - timedelta(hours=h)).isoformat(), temp=22.0, precip=1.0, et0=0.2)
        for h in range(48)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._derive_weather_daily_async(UUID(farm_id), tenant.schema_name)
    finally:
        weather_tasks.reset_provider_factory()

    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    ctx = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        since = (date.today() - timedelta(days=2)).isoformat()
        until = (date.today() + timedelta(days=1)).isoformat()
        resp = await client.get(
            f"/api/v1/blocks/{block_id}/weather/derived",
            params={"since": since, "until": until},
        )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) >= 1
    for r in rows:
        assert r["et0_mm_daily"] is not None
        assert r["gdd_base10"] is not None
