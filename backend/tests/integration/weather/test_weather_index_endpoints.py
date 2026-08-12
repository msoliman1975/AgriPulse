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


async def _seed_forecast(
    admin_session: AsyncSession, schema: str, farm_id: UUID, *, days: int = 4
) -> None:
    """`days` of forecast temperature starting tomorrow, values 40 upward.

    Far above the observed 20..29 so a forecast value showing up where an
    observed one belongs is unmistakable rather than plausible.
    """
    today = datetime.now(UTC).date()
    for offset in range(1, days + 1):
        await admin_session.execute(
            text(
                f'INSERT INTO "{schema}".weather_index_daily '
                f"(farm_id, date, index_code, value, value_aux, is_forecast) "
                f"VALUES (:fid, :d, 'temperature', :v, '{{}}'::jsonb, TRUE)"
            ),
            {"fid": farm_id, "d": today + timedelta(days=offset), "v": Decimal(40 + offset)},
        )
    await admin_session.commit()


@pytest.mark.asyncio
async def test_timeseries_carries_the_forecast_half(admin_session: AsyncSession) -> None:
    """The series continues past today, and says which points are forecast.

    This is the endpoint half of the reported gap: the projection writing
    forward is worthless if the read surface stops at the current date or
    hands the SPA no way to tell the two apart.
    """
    tenant, farm_id, app = await _bootstrap(admin_session, "wx-api-ts-fc")
    await _seed(admin_session, tenant.schema_name, UUID(farm_id))
    await _seed_forecast(admin_session, tenant.schema_name, UUID(farm_id))

    today = datetime.now(UTC).date()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/farms/{farm_id}/weather-indices/temperature/timeseries",
            params={"to": (today + timedelta(days=6)).isoformat()},
        )
    assert resp.status_code == 200, resp.text
    points = resp.json()["points"]
    assert len(points) == 14

    forecast = [p for p in points if p["is_forecast"]]
    observed = [p for p in points if not p["is_forecast"]]
    assert len(forecast) == 4
    assert len(observed) == 10
    # Still one ascending list, with the forward half strictly after today.
    assert [p["date"] for p in points] == sorted(p["date"] for p in points)
    assert min(p["date"] for p in forecast) > today.isoformat()


@pytest.mark.asyncio
async def test_summary_ignores_the_forecast_half(admin_session: AsyncSession) -> None:
    """ "Now" on the strip is the last OBSERVED day, not the horizon's end.

    The summary takes the last row of each series, so once the projection
    started writing days ahead an unfiltered read would headline a value
    four days from now as the farm's current temperature.
    """
    tenant, farm_id, app = await _bootstrap(admin_session, "wx-api-summary-fc")
    await _seed(admin_session, tenant.schema_name, UUID(farm_id))
    await _seed_forecast(admin_session, tenant.schema_name, UUID(farm_id))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/v1/farms/{farm_id}/weather-indices/summary")
    assert resp.status_code == 200, resp.text
    temp = next(e for e in resp.json()["indices"] if e["index_code"] == "temperature")
    assert Decimal(temp["value"]) == Decimal("29")  # not 41..44
    assert temp["latest_date"] == datetime.now(UTC).date().isoformat()


@pytest.mark.asyncio
async def test_summary_order_covers_every_catalog_index(admin_session: AsyncSession) -> None:
    """The summary's hard-coded order must match the catalog exactly.

    `humidity` was seeded as the eighth index by public migration 0049 and
    never added to `_WEATHER_INDEX_ORDER`, so it was computed, stored and
    charted but silently absent from the strip. Nothing failed — the loop
    just never asked for it. This test is the lock-step check that makes
    the next such addition break loudly.
    """
    from app.modules.weather.router import _WEATHER_INDEX_ORDER

    codes = [
        r[0]
        for r in (
            await admin_session.execute(
                text(
                    "SELECT code FROM public.weather_indices_catalog "
                    "WHERE is_active = TRUE AND deleted_at IS NULL "
                    "ORDER BY sort_order ASC"
                )
            )
        ).all()
    ]
    assert list(_WEATHER_INDEX_ORDER) == codes


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
