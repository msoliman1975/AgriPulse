"""POST /blocks/{id}/weather/refresh enqueues fetch_weather per active provider.

Two contracts asserted here:

  1. The HTTP response carries `queued_farm_ids` and the refresh enqueues
     one `fetch_weather` per distinct active provider on the block's farm.
  2. The task body itself, run against a fake provider, writes
     observations + forecasts and is idempotent on re-run (gate criterion).
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


def _fake_result() -> FetchResult:
    """Two past hours + two future hours, all UTC. The hypertable
    write path is what we're testing — values are arbitrary."""
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = (
        HourlyObservation(
            time=now - timedelta(hours=2),
            air_temp_c=Decimal("21.5"),
            humidity_pct=Decimal("60.00"),
            precipitation_mm=Decimal("0.00"),
            et0_mm=Decimal("0.20"),
        ),
        HourlyObservation(
            time=now - timedelta(hours=1),
            air_temp_c=Decimal("22.0"),
            humidity_pct=Decimal("58.00"),
        ),
    )
    fc = (
        HourlyForecast(
            time=now + timedelta(hours=1),
            air_temp_c=Decimal("22.5"),
            precipitation_mm=Decimal("0.00"),
        ),
        HourlyForecast(
            time=now + timedelta(hours=2),
            air_temp_c=Decimal("23.0"),
            precipitation_probability_pct=Decimal("10.00"),
        ),
    )
    return FetchResult(
        forecast_issued_at=now,
        observations=obs,
        forecasts=fc,
    )


class _FakeProvider:
    """Stub WeatherProvider — returns a hard-coded FetchResult."""

    code = "open_meteo"

    def __init__(self, result: FetchResult | None = None) -> None:
        self._result = result or _fake_result()

    async def fetch(self, **_: Any) -> FetchResult:
        return self._result

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_refresh_enqueues_fetch_per_provider(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-refresh-http",
        name="Weather Refresh HTTP",
        contact_email="ops@weather-refresh-http.test",
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
        _farm_id, block_id = await create_farm_and_block(client)
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        assert sub_resp.status_code == 201, sub_resp.text

        captured: list[tuple[Any, ...]] = []

        original_delay = weather_tasks.fetch_weather.delay

        def _capture(*args: object, **kwargs: object) -> None:
            captured.append(tuple(args))

        weather_tasks.fetch_weather.delay = _capture  # type: ignore[method-assign]
        try:
            resp = await client.post(f"/api/v1/blocks/{block_id}/weather/refresh")
        finally:
            weather_tasks.fetch_weather.delay = original_delay  # type: ignore[method-assign]

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert len(body["queued_farm_ids"]) == 1
    assert len(captured) == 1
    # args: (farm_id, tenant_schema, provider_code)
    assert captured[0][1] == tenant.schema_name
    assert captured[0][2] == "open_meteo"


@pytest.mark.asyncio
async def test_fetch_weather_writes_observations_and_forecasts(
    admin_session: AsyncSession,
) -> None:
    """Direct invocation of the task body: writes hypertable rows, touches sub markers."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-fetch-task",
        name="Weather Fetch Task",
        contact_email="ops@weather-fetch-task.test",
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
        sub_resp = await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )
        assert sub_resp.status_code == 201, sub_resp.text
        sub_id = sub_resp.json()["id"]

    weather_tasks.set_provider_factory(lambda _code: _FakeProvider())
    try:
        result = await weather_tasks._fetch_weather_async(
            UUID(farm_id), tenant.schema_name, "open_meteo"
        )
    finally:
        weather_tasks.reset_provider_factory()

    assert result["status"] == "succeeded"
    assert result["observations_inserted"] == 2
    assert result["forecasts_inserted"] == 2

    # Hypertable rows landed.
    obs_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".weather_observations')
        )
    ).scalar_one()
    assert obs_count == 2

    fc_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".weather_forecasts')
        )
    ).scalar_one()
    assert fc_count == 2

    # Subscription markers were touched.
    sub_row = (
        await admin_session.execute(
            text(
                f'SELECT last_attempted_at, last_successful_ingest_at FROM "{tenant.schema_name}".'
                "weather_subscriptions WHERE id = :id"
            ),
            {"id": UUID(sub_id)},
        )
    ).one()
    assert sub_row[0] is not None
    assert sub_row[1] is not None


@pytest.mark.asyncio
async def test_fetch_weather_idempotent_on_rerun(admin_session: AsyncSession) -> None:
    """Re-running fetch_weather with the same data is a no-op on hypertables.

    Observations dedupe on (time, farm_id, provider_code); forecasts on the
    same plus forecast_issued_at. So re-fetching the SAME forecast issuance
    inserts zero new rows. Re-fetching with a DIFFERENT issuance keeps the
    history (per the locked decision: keep all forecast snapshots).
    """
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-fetch-idemp",
        name="Weather Fetch Idempotent",
        contact_email="ops@weather-fetch-idemp.test",
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
        await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )

    fixed = _fake_result()  # same forecast_issued_at across both runs
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(fixed))
    try:
        first = await weather_tasks._fetch_weather_async(
            UUID(farm_id), tenant.schema_name, "open_meteo"
        )
        second = await weather_tasks._fetch_weather_async(
            UUID(farm_id), tenant.schema_name, "open_meteo"
        )
    finally:
        weather_tasks.reset_provider_factory()

    assert first["observations_inserted"] == 2
    assert first["forecasts_inserted"] == 2
    assert second["observations_inserted"] == 0
    assert second["forecasts_inserted"] == 0

    obs_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".weather_observations')
        )
    ).scalar_one()
    assert obs_count == 2


@pytest.mark.asyncio
async def test_fetch_weather_keeps_all_forecast_issuances(
    admin_session: AsyncSession,
) -> None:
    """Two runs with different forecast_issued_at retain BOTH snapshots."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="weather-fc-history",
        name="Weather Forecast History",
        contact_email="ops@weather-fc-history.test",
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
        await client.post(
            f"/api/v1/blocks/{block_id}/weather/subscriptions",
            json={"provider_code": "open_meteo"},
        )

    first = _fake_result()
    second = FetchResult(
        forecast_issued_at=first.forecast_issued_at + timedelta(hours=1),
        observations=first.observations,
        forecasts=first.forecasts,
    )

    # Use a stateful factory so consecutive calls return different issuances.
    calls = iter([first, second])
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(next(calls)))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
    finally:
        weather_tasks.reset_provider_factory()

    fc_count = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".weather_forecasts')
        )
    ).scalar_one()
    # Two forecasts x two issuances = four rows.
    assert fc_count == 4

    issuances = (
        await admin_session.execute(
            text(
                f'SELECT DISTINCT forecast_issued_at FROM "{tenant.schema_name}".'
                "weather_forecasts"
            )
        )
    ).all()
    assert len(issuances) == 2
