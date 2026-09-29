"""A forecast for each replayed morning, taken from what then happened.

Nobody stored the forecasts issued in the past, and the weather backfill
fetches observations only. Two mango trees read the next 72 hours, so a
replay without forecasts sends every one of those walks down its missing
branch for two years.

This step writes, for the simulated day, one issuance at 00:00 UTC that
covers the next 96 hours, copied from the observed hours. It is a perfect
forecast, which a real one never is. That is acceptable for a demo build
tenant and for nothing else, and the step lives here for that reason.

The snapshot reads only issuances at or before the clock, so a later
morning's copy never reaches an earlier day.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import text

from app.shared import clock
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_HORIZON_HOURS = 96


def hindcast_for_tenant(tenant_schema: str) -> dict[str, int]:
    return _run(_hindcast_async(tenant_schema))


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


async def _hindcast_async(tenant_schema: str) -> dict[str, int]:
    issued = datetime.combine(clock.today(), time(0), tzinfo=UTC)
    safe = sanitize_tenant_schema(tenant_schema)
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
        result = await session.execute(
            text(
                """
                INSERT INTO weather_forecasts (
                    time, forecast_issued_at, farm_id, provider_code,
                    air_temp_c, humidity_pct, precipitation_mm,
                    precipitation_probability_pct, wind_speed_m_s,
                    solar_radiation_w_m2, et0_mm
                )
                SELECT o.time, :issued, o.farm_id, o.provider_code,
                       o.air_temp_c, o.humidity_pct, o.precipitation_mm,
                       CASE WHEN o.precipitation_mm > 0.1 THEN 100 ELSE 0 END,
                       o.wind_speed_m_s, o.solar_radiation_w_m2, o.et0_mm
                  FROM weather_observations o
                 WHERE o.time >= :issued
                   AND o.time < :issued + make_interval(hours => :horizon)
                ON CONFLICT DO NOTHING
                """
            ),
            {"issued": issued, "horizon": _HORIZON_HOURS},
        )
    return {"forecast_hours_written": int(getattr(result, "rowcount", 0) or 0)}
