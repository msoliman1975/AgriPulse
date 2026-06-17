"""End-to-end tests for the PR-W4 weather-index read endpoints.

  GET /api/v1/farms/{farm_id}/weather-indices/{code}/timeseries
  GET /api/v1/farms/{farm_id}/weather-indices/summary

Both farm-scoped and gated on `weather.read`. Rows are seeded directly
into `weather_index_daily` / `weather_index_baselines` so the test
doesn't depend on the ingest + projection pipeline.
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


async def _seed(admin_session: AsyncSession, schema: str, farm_id: UUID) -> None:
    """10 days of temperature ending today (20..29) + a baseline for today."""
    today = datetime.now(UTC).date()
    for offset in range(10):
        d = today - timedelta(days=9 - offset)
        value = Decimal(20 + offset)
        # Stamp a known z-score on the latest row so the summary can echo it.
        dev = "1.5" if offset == 9 else None
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".weather_index_daily '
                f"(farm_id, date, index_code, value, value_aux, baseline_deviation) "
                f"VALUES (:fid, :d, 'temperature', :v, '{{}}'::jsonb, :dev)"
            ),
            {"fid": farm_id, "d": d, "v": value, "dev": Decimal(dev) if dev else None},
        )
    await admin_session.execute(
        text(
            f'INSERT INTO "{schema}".weather_index_baselines '
            f"(farm_id, index_code, day_of_year, baseline_mean, baseline_std, "
            f"sample_count, window_days, years_observed) "
            f"VALUES (:fid, 'temperature', :doy, 24, 3, 5, 7, 3)"
        ),
        {"fid": farm_id, "doy": today.timetuple().tm_yday},
    )
    await admin_session.commit()


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[Any, str, Any]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug, name=f"WX api {slug}", contact_email=f"ops@{slug}.test"
    )
    user_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id, _block_id = await create_farm_and_block(client)
    return tenant, farm_id, app


@pytest.mark.asyncio
async def test_timeseries_returns_series_with_climatology(admin_session: AsyncSession) -> None:
    tenant, farm_id, app = await _bootstrap(admin_session, "wx-api-ts")
    await _seed(admin_session, tenant.schema_name, UUID(farm_id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-indices/temperature/timeseries")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["farm_id"] == farm_id
    assert body["index_code"] == "temperature"
    points = body["points"]
    assert len(points) == 10
    # Ascending by date.
    dates = [p["date"] for p in points]
    assert dates == sorted(dates)
    # The latest day's DOY has a baseline, so its band is populated.
    latest = points[-1]
    assert Decimal(latest["value"]) == Decimal("29")
    assert Decimal(latest["baseline_mean"]) == Decimal("24")
    assert Decimal(latest["baseline_std"]) == Decimal("3")
    assert Decimal(latest["zscore"]) == Decimal("1.5")


@pytest.mark.asyncio
async def test_summary_latest_zscore_and_trend(admin_session: AsyncSession) -> None:
    tenant, farm_id, app = await _bootstrap(admin_session, "wx-api-summary")
    await _seed(admin_session, tenant.schema_name, UUID(farm_id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-indices/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["farm_id"] == farm_id
    temp = next(e for e in body["indices"] if e["index_code"] == "temperature")
    assert Decimal(temp["value"]) == Decimal("29")
    assert Decimal(temp["zscore"]) == Decimal("1.5")
    # latest (29, today) minus the value 7 days earlier (22) = 7.
    assert Decimal(temp["trend_7d_delta"]) == Decimal("7")


@pytest.mark.asyncio
async def test_timeseries_unknown_index_is_empty(admin_session: AsyncSession) -> None:
    tenant, farm_id, app = await _bootstrap(admin_session, "wx-api-unknown")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-indices/nope/timeseries")
    assert resp.status_code == 200, resp.text
    assert resp.json()["points"] == []


@pytest.mark.asyncio
async def test_weather_index_endpoints_require_capability(admin_session: AsyncSession) -> None:
    """A user with no weather.read on the farm is denied."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="wx-api-rbac", name="WX api rbac", contact_email="ops@rbac.test"
    )
    admin_id = uuid4()
    await create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=admin_id)
    admin_ctx = make_context(
        user_id=admin_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    app_admin = build_app(admin_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=app_admin), base_url="http://test"
    ) as client:
        farm_id, _ = await create_farm_and_block(client)

    # A farm-scoped viewer with an empty scope set has no caps on this farm.
    nobody = make_context(
        user_id=uuid4(),
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(),
    )
    app_nobody = build_app(nobody)
    async with AsyncClient(
        transport=ASGITransport(app=app_nobody), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-indices/summary")
    assert resp.status_code in (403, 404), resp.text
