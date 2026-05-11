"""Celery tasks for the weather ingestion pipeline.

Two tasks:

    fetch_weather(farm_id, tenant_schema, provider_code)
        Fetch one (farm, provider) pair: resolve the farm's centroid,
        call the provider, write observations + forecasts idempotently,
        touch every active subscription's `last_*_at` markers.

    discover_due_subscriptions()
        Beat-only sweep. Walks every active tenant, finds (farm_id,
        provider_code) pairs whose oldest active subscription is overdue,
        enqueues `fetch_weather` for each. Dedup is done in SQL — many
        per-block subscriptions on the same farm collapse to one fetch.

Each task wraps an async core in `asyncio.run` and disposes the engine
afterwards so each Celery invocation gets a fresh asyncpg pool bound
to its own loop (same pattern as imagery/tasks.py).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.audit import get_audit_service
from app.modules.weather.derivations import (
    HourlyRow,
    aggregate_one_day,
    bucket_hourly_by_local_date,
    cumulative_gdd_base10_for_season,
    rolling_precip_total,
)
from app.modules.weather.providers.open_meteo import OpenMeteoProvider
from app.modules.weather.providers.protocol import WeatherProvider
from app.modules.weather.repository import WeatherRepository
from app.modules.weather.timezone import tz_for_centroid
from app.shared.db.ids import uuid7
from app.shared.db.session import AsyncSessionLocal, dispose_engine, sanitize_tenant_schema

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async task body and dispose the engine on exit.

    See `imagery/tasks.py:_run_task` for the rationale — without
    per-task disposal, the asyncpg pool retains references to a
    closed event loop and the next task's checkout fails.
    """

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


# --- DI seam (overridable in tests) ----------------------------------------


def _make_provider(provider_code: str) -> WeatherProvider:
    """Construct a provider for the given code.

    Open-Meteo is the only provider in PR-B. Adding another provider is
    one branch here plus a `public.weather_providers` row.
    """
    if provider_code == "open_meteo":
        return OpenMeteoProvider()
    raise ValueError(f"Unsupported weather provider_code: {provider_code!r}")


_provider_factory: Callable[[str], WeatherProvider] = _make_provider


def set_provider_factory(factory: Callable[[str], WeatherProvider]) -> None:
    """Test seam: swap in a mock provider builder."""
    global _provider_factory
    _provider_factory = factory


def reset_provider_factory() -> None:
    global _provider_factory
    _provider_factory = _make_provider


# --- Helpers ---------------------------------------------------------------


def _classify_error(exc: BaseException) -> str:
    """Short categorized code for the attempt log.

    The full exception message goes in `error_message`; this code is
    what the UI filters/groups on, so it has to be coarse and stable.
    """
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg:
        return "timeout"
    if "connect" in name or "connect" in msg:
        return "connection_error"
    if any(s in msg for s in ("400", "401", "403", "404", "422")):
        return "http_4xx"
    if any(s in msg for s in ("500", "502", "503", "504")):
        return "http_5xx"
    if "json" in msg or "decode" in msg or "parse" in msg:
        return "parse_error"
    return "provider_error"


async def _set_tenant_context(session: Any, tenant_schema: str) -> None:
    safe = sanitize_tenant_schema(tenant_schema)
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
        {"v": safe},
    )


# --- fetch_weather ---------------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.fetch_weather",
    bind=False,
    ignore_result=True,
)
def fetch_weather(farm_id: str, tenant_schema: str, provider_code: str) -> dict[str, Any]:
    """Beat- or refresh-driven entry point for one (farm, provider) pair."""
    return _run_task(_fetch_weather_async(UUID(farm_id), tenant_schema, provider_code))


async def _fetch_weather_async(
    farm_id: UUID, tenant_schema: str, provider_code: str
) -> dict[str, Any]:
    settings = get_settings()
    audit = get_audit_service()
    factory = AsyncSessionLocal()

    # Step 1: resolve farm centroid + open an attempt row per subscription.
    started_at = datetime.now(UTC)
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)

        centroid = await repo.get_farm_centroid(farm_id)
        if centroid is None:
            _log.warning(
                "weather_fetch_farm_missing",
                farm_id=str(farm_id),
                tenant_schema=tenant_schema,
            )
            return {"farm_id": str(farm_id), "status": "farm_missing"}

        subs = await repo.list_active_subscriptions_for_farm(
            farm_id=farm_id, provider_code=provider_code
        )
        # One attempt row per (subscription, fetch) — keeps each block's
        # history independent even though the provider call is shared.
        attempts: list[dict[str, Any]] = []
        for s in subs:
            attempt_id = uuid7()
            await repo.open_attempt(
                attempt_id=attempt_id,
                subscription_id=s["id"],
                block_id=s["block_id"],
                farm_id=farm_id,
                provider_code=provider_code,
                started_at=started_at,
            )
            attempts.append({"id": attempt_id, "subscription_id": s["id"]})
        subscription_ids = tuple(s["id"] for s in subs)

    # Step 2: fetch from the provider. No DB session held during HTTP IO.
    provider = _provider_factory(provider_code)
    try:
        try:
            result = await provider.fetch(
                latitude=centroid["latitude"],
                longitude=centroid["longitude"],
                past_hours=settings.weather_past_hours,
                forecast_hours=settings.weather_forecast_hours,
            )
        except Exception as exc:
            now = datetime.now(UTC)
            error_code = _classify_error(exc)
            error_message = str(exc)
            async with factory() as session, session.begin():
                await _set_tenant_context(session, tenant_schema)
                repo = WeatherRepository(session)
                for sub_id in subscription_ids:
                    await repo.touch_subscription_attempt(
                        subscription_id=sub_id, attempted_at=now, success=False
                    )
                for a in attempts:
                    await repo.close_attempt(
                        attempt_id=a["id"],
                        completed_at=now,
                        status="failed",
                        error_code=error_code,
                        error_message=error_message,
                    )
            await audit.record(
                tenant_schema=tenant_schema,
                event_type="weather.fetch_failed",
                actor_user_id=None,
                actor_kind="system",
                subject_kind="farm",
                subject_id=farm_id,
                farm_id=farm_id,
                details={"provider_code": provider_code, "error": str(exc)},
            )
            _log.exception(
                "weather_fetch_failed",
                farm_id=str(farm_id),
                provider_code=provider_code,
            )
            return {"farm_id": str(farm_id), "status": "fetch_failed"}
    finally:
        await provider.aclose()

    # Step 3: write rows + touch subscription markers.
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        observations_inserted = await repo.upsert_observations(
            farm_id=farm_id,
            provider_code=provider_code,
            observations=result.observations,
        )
        forecasts_inserted = await repo.upsert_forecasts(
            farm_id=farm_id,
            provider_code=provider_code,
            forecast_issued_at=result.forecast_issued_at,
            forecasts=result.forecasts,
        )
        now = datetime.now(UTC)
        for sub_id in subscription_ids:
            await repo.touch_subscription_attempt(
                subscription_id=sub_id, attempted_at=now, success=True
            )
        total_rows = observations_inserted + forecasts_inserted
        for a in attempts:
            await repo.close_attempt(
                attempt_id=a["id"],
                completed_at=now,
                status="succeeded",
                rows_ingested=total_rows,
            )

    await audit.record(
        tenant_schema=tenant_schema,
        event_type="weather.fetch_succeeded",
        actor_user_id=None,
        actor_kind="system",
        subject_kind="farm",
        subject_id=farm_id,
        farm_id=farm_id,
        details={
            "provider_code": provider_code,
            "observations_inserted": observations_inserted,
            "forecasts_inserted": forecasts_inserted,
            "forecast_issued_at": result.forecast_issued_at.isoformat(),
        },
    )

    # Chain the daily derivation task. Failure to derive doesn't roll
    # back the observation/forecast write — the next fetch will retry,
    # and the cumulative/rolling fields are deterministic from
    # observations alone, so partial state self-heals.
    derive_weather_daily.delay(str(farm_id), tenant_schema)

    return {
        "farm_id": str(farm_id),
        "status": "succeeded",
        "observations_inserted": observations_inserted,
        "forecasts_inserted": forecasts_inserted,
    }


# --- derive_weather_daily --------------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.derive_weather_daily",
    bind=False,
    ignore_result=True,
)
def derive_weather_daily(farm_id: str, tenant_schema: str) -> dict[str, Any]:
    """Recompute today + yesterday `weather_derived_daily` rows for a farm.

    "Day" is bucketed in the farm's centroid timezone — see
    :mod:`weather.timezone`. The rolling 7d/30d windows pull from
    historical observations, so this task can run without prior
    derivation rows existing (cold-start safe).
    """
    return _run_task(_derive_weather_daily_async(UUID(farm_id), tenant_schema))


async def _derive_weather_daily_async(farm_id: UUID, tenant_schema: str) -> dict[str, Any]:
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)

        centroid = await repo.get_farm_centroid(farm_id)
        if centroid is None:
            return {"farm_id": str(farm_id), "status": "farm_missing"}
        tz = tz_for_centroid(centroid["latitude"], centroid["longitude"])

        # Window: 30 days back through tomorrow (so the rolling 30d window
        # for "today" has data, and the partial day self-corrects as more
        # observations arrive). Times are tz-aware UTC (TIMESTAMPTZ).
        now_utc = datetime.now(UTC)
        until_utc = now_utc + timedelta(days=1)
        since_utc = now_utc - timedelta(days=31)

        obs_rows = await repo.read_observations(
            farm_id=farm_id,
            provider_code=None,
            since=since_utc,
            until=until_utc,
        )

    # Aggregate per local-date from the in-memory rows. Same DB session
    # pattern as imagery's compute_indices: HTTP/CPU work outside any
    # held transaction, then re-open for writes.
    hourly = tuple(
        HourlyRow(
            time=r["time"],
            air_temp_c=r["air_temp_c"],
            precipitation_mm=r["precipitation_mm"],
            et0_mm=r["et0_mm"],
        )
        for r in obs_rows
    )
    by_local_date = bucket_hourly_by_local_date(hourly, tz)
    daily = {d: aggregate_one_day(rows, d) for d, rows in by_local_date.items()}

    # Recompute today + yesterday in farm-local time. Tomorrow is left
    # alone — the row would be all-NaN until observations land.
    today_local = datetime.now(tz).date()
    yesterday_local = today_local - timedelta(days=1)
    targets = (yesterday_local, today_local)

    written = 0
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        for d in targets:
            day = daily.get(d)
            if day is None:
                continue
            await repo.upsert_derived_daily(
                farm_id=farm_id,
                date=d,
                temp_min_c=day.temp_min_c,
                temp_max_c=day.temp_max_c,
                temp_mean_c=day.temp_mean_c,
                precip_mm_daily=day.precip_mm_daily,
                et0_mm_daily=day.et0_mm_daily,
                gdd_base10=day.gdd_base10,
                gdd_base15=day.gdd_base15,
                gdd_cumulative_base10_season=cumulative_gdd_base10_for_season(daily, d),
                precip_mm_7d=rolling_precip_total(daily, d, window_days=7),
                precip_mm_30d=rolling_precip_total(daily, d, window_days=30),
            )
            written += 1

    return {
        "farm_id": str(farm_id),
        "status": "succeeded",
        "days_written": written,
    }


# --- discover_due_subscriptions (Beat sweep) -------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.discover_due_subscriptions",
    bind=False,
    ignore_result=True,
)
def discover_due_subscriptions() -> dict[str, int]:
    return _run_task(_discover_due_subscriptions_async())


async def _discover_due_subscriptions_async() -> dict[str, int]:
    settings = get_settings()
    factory = AsyncSessionLocal()

    # Step 1: list active tenants from public.tenants.
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            )
        ).all()
    tenant_schemas = [str(r[0]) for r in rows]

    enqueued = 0
    for tenant_schema in tenant_schemas:
        try:
            sanitize_tenant_schema(tenant_schema)
        except ValueError:
            continue
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            repo = WeatherRepository(session)
            due = await repo.list_due_farm_provider_pairs(
                default_cadence_hours=settings.weather_default_cadence_hours,
                now=datetime.now(UTC),
            )
        for farm_id, provider_code in due:
            fetch_weather.delay(str(farm_id), tenant_schema, provider_code)
            enqueued += 1
    return {"tenants_scanned": len(tenant_schemas), "enqueued": enqueued}
