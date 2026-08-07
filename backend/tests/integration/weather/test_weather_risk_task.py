"""Integration: `compute_weather_risk_for_tenant` materialises weather_risk_daily.

Seeds a mango block (at a susceptible stage) + 15 days of hourly observations,
runs fetch + the per-tenant risk compute, and asserts the three mango risk
models land rows with the expected banding.
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


def _obs(when: datetime, hour_of_day: int) -> HourlyObservation:
    # Warm (24 C), humid (70 %), DRY: favours powdery mildew + fruit fly, but
    # not anthracnose (needs free moisture).
    daytime = 6 <= hour_of_day <= 18
    return HourlyObservation(
        time=when,
        air_temp_c=Decimal("24.0"),
        humidity_pct=Decimal("70"),
        precipitation_mm=Decimal("0"),
        wind_speed_m_s=Decimal("2.0"),
        wind_direction_deg=Decimal("180"),
        solar_radiation_w_m2=Decimal("500") if daytime else Decimal("0"),
        et0_mm=Decimal("0.2"),
    )


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, str, str]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"WR task {slug}", contact_email=f"ops@{slug}.test"
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
    return tenant, farm_id, block_id


async def _assign_mango_crop(admin_session: AsyncSession, schema: str, block_id: str) -> None:
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".block_crops '
            f"(id, block_id, crop_id, crop_path, season_label, is_current, status, "
            f" growth_stage, canopy_size_class, effective_from, effective_to) "
            f"VALUES (:id, :block, :crop, 'mango.keitt.large', '2026', TRUE, 'growing', "
            f" 'fruit_set', 'large', CURRENT_DATE, NULL)"
        ),
        {"id": uuid4(), "block": UUID(block_id), "crop": uuid4()},
    )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_compute_writes_mango_risk_rows(admin_session: AsyncSession) -> None:
    tenant, farm_id, block_id = await _bootstrap(admin_session, "wr-task-writes")
    await _assign_mango_crop(admin_session, tenant.schema_name, block_id)

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _obs(now - timedelta(hours=h), (now - timedelta(hours=h)).hour) for h in range(15 * 24)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        summary = await weather_tasks._compute_weather_risk_for_tenant_async(tenant.schema_name)
    finally:
        weather_tasks.reset_provider_factory()

    assert summary["blocks_scored"] >= 1
    assert summary["rows_written"] >= 1

    rows = (
        await admin_session.execute(
            text(
                f"SELECT risk_code, score, level "
                f'FROM "{tenant.schema_name}".weather_risk_daily '
                f"WHERE block_id = :bid ORDER BY risk_code"
            ),
            {"bid": UUID(block_id)},
        )
    ).all()
    by_code = {r.risk_code: r for r in rows}
    assert set(by_code) == {"powdery_mildew", "anthracnose", "fruit_fly"}
    # Warm-humid-dry at a susceptible stage -> powdery mildew saturates.
    assert by_code["powdery_mildew"].score == 100
    assert by_code["powdery_mildew"].level == "high"
    # Dry -> anthracnose finds no leaf wetness.
    assert by_code["anthracnose"].score == 0
    assert by_code["anthracnose"].level == "low"


@pytest.mark.asyncio
async def test_compute_is_idempotent(admin_session: AsyncSession) -> None:
    tenant, farm_id, block_id = await _bootstrap(admin_session, "wr-task-idemp")
    await _assign_mango_crop(admin_session, tenant.schema_name, block_id)

    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    obs = tuple(
        _obs(now - timedelta(hours=h), (now - timedelta(hours=h)).hour) for h in range(15 * 24)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))

    async def _count() -> int:
        return (
            await admin_session.execute(
                text(
                    f'SELECT count(*) FROM "{tenant.schema_name}".weather_risk_daily '
                    f"WHERE block_id = :bid"
                ),
                {"bid": UUID(block_id)},
            )
        ).scalar_one()

    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), tenant.schema_name, "open_meteo")
        await weather_tasks._compute_weather_risk_for_tenant_async(tenant.schema_name)
        first = await _count()
        await weather_tasks._compute_weather_risk_for_tenant_async(tenant.schema_name)
        second = await _count()
    finally:
        weather_tasks.reset_provider_factory()
    assert first > 0
    assert first == second
