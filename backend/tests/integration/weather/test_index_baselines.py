"""Integration tests for the PR-W3 climatology baseline sweep + backfill.

  * `recompute_weather_baselines_for_tenant` — builds farm-scoped
    `weather_index_baselines` from `weather_index_daily` history and
    re-derives the z-score on existing rows.
  * `backfill_weather_indices` — reprojects a wide window of observations
    so the sweep has multi-day history to chew on.
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


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, str, str]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"WX base {slug}", contact_email=f"ops@{slug}.test"
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


@pytest.mark.asyncio
async def test_baseline_sweep_builds_baselines_and_zscores(admin_session: AsyncSession) -> None:
    tenant, farm_id, _ = await _bootstrap(admin_session, "wx-base-sweep")
    schema = tenant.schema_name

    # Three years of mid-June temperature on (nearly) the same DOY. The
    # ±7-day window folds the leap-year DOY drift together, so DOY ~166
    # ends up with all three samples — enough to emit a baseline.
    history = [
        (date(2024, 6, 15), "20"),
        (date(2025, 6, 15), "24"),
        (date(2026, 6, 15), "28"),
    ]
    for d, v in history:
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".weather_index_daily '
                f"(farm_id, date, index_code, value, value_aux) "
                f"VALUES (:fid, :d, 'temperature', :v, '{{}}'::jsonb)"
            ),
            {"fid": UUID(farm_id), "d": d, "v": Decimal(v)},
        )
    await admin_session.commit()

    out = await weather_tasks._recompute_weather_baselines_for_tenant_async(schema)
    assert out["baselines_written"] > 0, out
    assert out["deviations_updated"] >= 3, out

    base_count = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{schema}".weather_index_baselines '
                f"WHERE farm_id = :fid AND index_code = 'temperature'"
            ),
            {"fid": UUID(farm_id)},
        )
    ).scalar_one()
    assert base_count > 0

    # Mean is 24: the 28 row sits above (positive z), the 20 row below.
    devs = {
        r.date: r.baseline_deviation
        for r in (
            await admin_session.execute(
                text(
                    f'SELECT date, baseline_deviation FROM "{schema}".weather_index_daily '
                    f"WHERE farm_id = :fid AND index_code = 'temperature'"
                ),
                {"fid": UUID(farm_id)},
            )
        ).all()
    }
    assert devs[date(2026, 6, 15)] is not None
    assert devs[date(2026, 6, 15)] > 0
    assert devs[date(2024, 6, 15)] is not None
    assert devs[date(2024, 6, 15)] < 0


@pytest.mark.asyncio
async def test_backfill_projects_many_days(admin_session: AsyncSession) -> None:
    tenant, farm_id, _ = await _bootstrap(admin_session, "wx-base-backfill")
    schema = tenant.schema_name

    # 10 days of hourly observations (one reading at noon each day is
    # enough to define each local day).
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    obs = tuple(
        HourlyObservation(
            time=now - timedelta(days=day_offset),
            air_temp_c=Decimal("25.0"),
            precipitation_mm=Decimal("0.0"),
            et0_mm=Decimal("4.0"),
            solar_radiation_w_m2=Decimal("600"),
            wind_speed_m_s=Decimal("2.0"),
            wind_direction_deg=Decimal("90"),
            humidity_pct=Decimal("40"),
        )
        for day_offset in range(10)
    )
    result = FetchResult(forecast_issued_at=now, observations=obs, forecasts=())
    weather_tasks.set_provider_factory(lambda _code: _FakeProvider(result))
    try:
        await weather_tasks._fetch_weather_async(UUID(farm_id), schema, "open_meteo")
        # The regular derive only touches today+yesterday; backfill covers all.
        out = await weather_tasks._backfill_weather_indices_async(UUID(farm_id), schema, 15)
    finally:
        weather_tasks.reset_provider_factory()

    assert out["status"] == "succeeded", out
    distinct_days = (
        await admin_session.execute(
            text(
                f'SELECT count(DISTINCT date) FROM "{schema}".weather_index_daily '
                f"WHERE farm_id = :fid AND index_code = 'temperature'"
            ),
            {"fid": UUID(farm_id)},
        )
    ).scalar_one()
    # At least ~9 of the 10 seeded days (tz bucketing may drop one edge day).
    assert distinct_days >= 9, distinct_days
