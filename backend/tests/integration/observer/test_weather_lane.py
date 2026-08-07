"""The weather lane.

Weather has no scenes and no pixels, so the interesting question is whether
the ribbon's denominators still mean anything — and whether the one genuinely
new diagnostic works: hour coverage.

A day derived from nine hourly rows produces a confident-looking ET₀ that is
wrong, and nothing else in the product distinguishes it from a full day. Two
tests here are about exactly that day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import PlatformRole

from .conftest import WINDOW_FROM, WINDOW_TO, Scenario, build_app, make_context

pytestmark = [pytest.mark.integration]

_BASE = "/api/v1/admin/observer"

# The thin day: 9 hours, 06:00-14:00, with a derived row anyway.
THIN_DAY = WINDOW_FROM + timedelta(days=1)
FULL_DAY = WINDOW_FROM + timedelta(days=2)


def _platform_client() -> AsyncClient:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _window() -> dict[str, str]:
    return {"from": WINDOW_FROM.isoformat(), "to": WINDOW_TO.isoformat()}


async def _seed_weather(session: AsyncSession, scenario: Scenario) -> None:
    """One thin day and one full day, both with derived + index rows."""
    await session.execute(text(f'SET search_path TO "{scenario.tenant_schema}", public'))

    for day, hours in ((THIN_DAY, range(6, 15)), (FULL_DAY, range(24))):
        for hour in hours:
            await session.execute(
                text(
                    """
                    INSERT INTO weather_observations (
                        time, farm_id, provider_code, air_temp_c, humidity_pct,
                        precipitation_mm, wind_speed_m_s, solar_radiation_w_m2, et0_mm
                    ) VALUES (
                        :t, CAST(:fid AS uuid), 'open_meteo', 27.4, 41.2,
                        0.0, 2.8, 248.0, 0.28
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"t": day.replace(hour=hour), "fid": str(scenario.farm_id)},
            )
        await session.execute(
            text(
                """
                INSERT INTO weather_derived_daily (
                    farm_id, date, et0_mm_daily, precip_mm_daily,
                    temp_min_c, temp_max_c, temp_mean_c
                ) VALUES (
                    CAST(:fid AS uuid), :d, 6.82, 0.0, 21.1, 33.8, 27.4
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {"fid": str(scenario.farm_id), "d": day.date()},
        )
        await session.execute(
            text(
                """
                INSERT INTO weather_index_daily (
                    farm_id, date, index_code, value, value_aux
                ) VALUES (
                    CAST(:fid AS uuid), :d, 'evapotranspiration', 6.82, '{}'::jsonb
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {"fid": str(scenario.farm_id), "d": day.date()},
        )

    # The scenario has no weather subscription of its own, and the attempt row
    # needs one to point at — without this the INSERT..SELECT below matches
    # nothing and silently writes zero rows.
    await session.execute(
        text(
            """
            INSERT INTO weather_subscriptions (block_id, provider_code, is_active)
            SELECT b.id, 'open_meteo', TRUE
              FROM blocks b
             WHERE b.farm_id = CAST(:fid AS uuid)
             LIMIT 1
            ON CONFLICT DO NOTHING
            """
        ),
        {"fid": str(scenario.farm_id)},
    )
    await session.execute(
        text(
            """
            INSERT INTO weather_ingestion_attempts (
                subscription_id, block_id, farm_id, provider_code,
                started_at, completed_at, status, rows_ingested
            )
            SELECT w.id, w.block_id, CAST(:fid AS uuid), 'open_meteo',
                   :t, :t, 'succeeded', 24
              FROM weather_subscriptions w
              JOIN blocks b ON b.id = w.block_id
             WHERE b.farm_id = CAST(:fid AS uuid)
             LIMIT 1
            """
        ),
        {"fid": str(scenario.farm_id), "t": FULL_DAY},
    )
    await session.commit()
    await session.execute(text("SET search_path TO public"))


# ---- the ribbon ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_farm_with_no_weather_subscription_says_so(scenario: Scenario) -> None:
    """Every zero on an unsubscribed farm is "never configured", not "broken".

    Without this flag an operator reads a wall of zeros as an outage.
    """
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/weather/overview",
            params={"farm_id": str(scenario.farm_id), **_window()},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subscribed"] is False
        assert all(s["count"] == 0 for s in body["stages"])


@pytest.mark.asyncio
async def test_the_weather_ribbon_denominates_hours_by_the_window(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """Observations are compared against the window's own hour count.

    A denominator derived from the stored rows could never show a gap — it
    would always be 100%.
    """
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/weather/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        stages = {s["key"]: s for s in body["stages"]}

        # 9 thin + 24 full = 33 hourly rows in a 31-day window.
        assert stages["observations"]["count"] == 33
        assert stages["observations"]["expected"] == int(
            (WINDOW_TO - WINDOW_FROM).total_seconds() // 3600
        )
        assert stages["observations"]["verdict"] == "bad"
        assert stages["derived"]["count"] == 2


@pytest.mark.asyncio
async def test_index_rows_are_denominated_by_the_catalog(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """A derived day that produced fewer index rows than the catalog has
    codes is a real gap, and only the catalog denominator surfaces it."""
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/weather/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        indices = {s["key"]: s for s in body["stages"]}["indices"]
        # 2 days x 1 index written, against 2 days x the whole catalog.
        assert indices["count"] == 2
        assert indices["expected"] == 2 * indices["detail"]["catalog_codes"]
        assert indices["verdict"] == "bad"


# ---- hour coverage ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_thin_day_with_a_derived_row_is_flagged(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The dangerous case: 9 of 24 hours, and a number computed anyway.

    Nothing downstream knows the difference, which is the whole reason this
    diagnostic exists.
    """
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/weather/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()

        thin = body["thin_days"]
        assert len(thin) == 1
        assert thin[0]["day"] == THIN_DAY.date().isoformat()
        assert thin[0]["hours"] == 9
        assert thin[0]["has_derived"] is True

        # And the response is explicit that nothing rejected it.
        assert body["derivation_enforces_floor"] is False
        assert body["coverage_floor_hours"] == 18


@pytest.mark.asyncio
async def test_a_full_day_is_not_flagged(scenario: Scenario, admin_session: AsyncSession) -> None:
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        body = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/weather/overview",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        coverage = {d["day"]: d for d in body["coverage"]}
        assert coverage[FULL_DAY.date().isoformat()]["hours"] == 24
        assert FULL_DAY.date().isoformat() not in {d["day"] for d in body["thin_days"]}


# ---- explain ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_explain_shows_the_hours_a_value_was_built_from(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """The weather counterpart of the pixel inspector.

    The hourly rows, the derived intermediate, the catalog definition — and
    the coverage that qualifies all three.
    """
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/weather/explain",
            params={
                "farm_id": str(scenario.farm_id),
                "index_code": "evapotranspiration",
                "day": THIN_DAY.date().isoformat(),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["hours_present"] == 9
        assert body["hours_expected"] == 24
        assert body["coverage_sufficient"] is False
        assert len(body["hourly"]) == 9
        # The intermediate the index was projected from, not just the answer.
        assert body["derived"]["et0_mm_daily"] is not None
        assert body["catalog"]["unit"]


@pytest.mark.asyncio
async def test_explain_of_a_missing_day_is_404(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/weather/explain",
            params={
                "farm_id": str(scenario.farm_id),
                "index_code": "evapotranspiration",
                "day": (WINDOW_TO + timedelta(days=5)).date().isoformat(),
            },
        )
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_index_days_report_the_hours_behind_each_value(
    scenario: Scenario, admin_session: AsyncSession
) -> None:
    """`source_hours` travels with every value, so a list of ET₀ numbers
    carries its own trustworthiness rather than needing a second lookup."""
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        rows = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/weather/index-days",
                params={
                    "farm_id": str(scenario.farm_id),
                    "index_code": "evapotranspiration",
                    **_window(),
                },
            )
        ).json()
        by_day = {r["date"]: r for r in rows}
        assert by_day[THIN_DAY.date().isoformat()]["source_hours"] == 9
        assert by_day[FULL_DAY.date().isoformat()]["source_hours"] == 24


@pytest.mark.asyncio
async def test_weather_overview_refuses_an_over_wide_window(scenario: Scenario) -> None:
    async with _platform_client() as client:
        now = datetime.now(UTC)
        r = await client.get(
            f"{_BASE}/tenants/{scenario.tenant_id}/weather/overview",
            params={
                "farm_id": str(scenario.farm_id),
                "from": (now - timedelta(days=4000)).isoformat(),
                "to": now.isoformat(),
            },
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_attempts_are_listed(scenario: Scenario, admin_session: AsyncSession) -> None:
    await _seed_weather(admin_session, scenario)
    async with _platform_client() as client:
        rows: list[dict[str, Any]] = (
            await client.get(
                f"{_BASE}/tenants/{scenario.tenant_id}/weather/attempts",
                params={"farm_id": str(scenario.farm_id), **_window()},
            )
        ).json()
        assert len(rows) == 1
        assert rows[0]["provider_code"] == "open_meteo"
        assert rows[0]["status"] == "succeeded"
