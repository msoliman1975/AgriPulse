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
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.audit import get_audit_service
from app.modules.indices.baselines import (
    HistoryRow,
    compute_baseline_deviation,
    compute_block_baselines,
)
from app.modules.integrations_health.error_codes import classify_error as _classify_error
from app.modules.weather.derivations import (
    DailyDerived,
    HourlyRow,
    aggregate_one_day,
    bucket_hourly_by_local_date,
    cumulative_gdd_base10_for_season,
    rolling_precip_total,
)
from app.modules.weather.index_projection import (
    IndexHourlyRow,
    RadiationWindDay,
    aggregate_radiation_wind_day,
    bucket_index_hourly_by_local_date,
    project_indices,
)
from app.modules.weather.providers.open_meteo import OpenMeteoProvider
from app.modules.weather.providers.protocol import WeatherProvider
from app.modules.weather.repository import WeatherRepository
from app.modules.weather.risk import RiskBlockContext, evaluate_risks
from app.modules.weather.risk_projection import build_risk_window
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


# `_classify_error` is imported at the top alongside other module imports;
# the alias is retained for backward compatibility with existing call sites.
# Classifier body lives in integrations_health.error_codes so imagery shares
# the same vocabulary - see PR-IH8.


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


# ±N-day calendar window the weather-index climatology aggregates over
# (mirrors the indices baseline window). One row per DOY needs ≥3 samples.
_WEATHER_BASELINE_WINDOW_DAYS = 7
# How far back `backfill_weather_indices` reprojects history into
# `weather_index_daily` so the climatology sweep has something to chew on.
_BACKFILL_WINDOW_DAYS = 400


def _aggregate_obs_window(
    obs_rows: tuple[dict[str, Any], ...], tz: Any
) -> tuple[dict[Any, DailyDerived], dict[Any, RadiationWindDay]]:
    """Aggregate a window of hourly observation rows into per-local-date
    `DailyDerived` (temp/precip/ET₀/GDD) + `RadiationWindDay` (radiation +
    wind) maps. Pure CPU — no DB. Shared by derive + backfill.
    """
    hourly = tuple(
        HourlyRow(
            time=r["time"],
            air_temp_c=r["air_temp_c"],
            precipitation_mm=r["precipitation_mm"],
            et0_mm=r["et0_mm"],
        )
        for r in obs_rows
    )
    daily = {
        d: aggregate_one_day(rows, d) for d, rows in bucket_hourly_by_local_date(hourly, tz).items()
    }

    # Radiation + wind aren't carried by DailyDerived (the GDD/ET path).
    idx_hourly = tuple(
        IndexHourlyRow(
            time=r["time"],
            solar_radiation_w_m2=r["solar_radiation_w_m2"],
            wind_speed_m_s=r["wind_speed_m_s"],
            wind_direction_deg=r["wind_direction_deg"],
            humidity_pct=r["humidity_pct"],
        )
        for r in obs_rows
    )
    radwind_by_date = {
        d: aggregate_radiation_wind_day(rows)
        for d, rows in bucket_index_hourly_by_local_date(idx_hourly, tz).items()
    }
    return daily, radwind_by_date


async def _persist_day(
    repo: WeatherRepository,
    *,
    farm_id: UUID,
    daily: dict[Any, DailyDerived],
    radwind_by_date: dict[Any, RadiationWindDay],
    day: Any,
) -> int:
    """Upsert one day's `weather_derived_daily` row + project its weather
    indices (with a z-score vs the climatology baseline). Caller guarantees
    ``daily[day]`` exists. Returns the number of index rows written.
    """
    row = daily[day]
    await repo.upsert_derived_daily(
        farm_id=farm_id,
        date=day,
        temp_min_c=row.temp_min_c,
        temp_max_c=row.temp_max_c,
        temp_mean_c=row.temp_mean_c,
        precip_mm_daily=row.precip_mm_daily,
        et0_mm_daily=row.et0_mm_daily,
        gdd_base10=row.gdd_base10,
        gdd_base15=row.gdd_base15,
        gdd_cumulative_base10_season=cumulative_gdd_base10_for_season(daily, day),
        precip_mm_7d=rolling_precip_total(daily, day, window_days=7),
        precip_mm_30d=rolling_precip_total(daily, day, window_days=30),
    )

    doy = day.timetuple().tm_yday
    indices_written = 0
    for proj in project_indices(day, daily, radwind_by_date.get(day)):
        baseline = await repo.read_index_baseline(
            farm_id=farm_id, index_code=proj.index_code, day_of_year=doy
        )
        deviation = (
            compute_baseline_deviation(
                value=proj.value,
                baseline_mean=baseline["baseline_mean"],
                baseline_std=baseline["baseline_std"],
            )
            if baseline is not None
            else None
        )
        await repo.upsert_weather_index_daily(
            farm_id=farm_id,
            date=day,
            index_code=proj.index_code,
            value=proj.value,
            value_min=proj.value_min,
            value_max=proj.value_max,
            value_aux=proj.value_aux,
            baseline_deviation=deviation,
        )
        indices_written += 1
    return indices_written


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
    daily, radwind_by_date = _aggregate_obs_window(obs_rows, tz)

    # Recompute today + yesterday in farm-local time. Tomorrow is left
    # alone — the row would be all-NaN until observations land.
    today_local = datetime.now(tz).date()
    yesterday_local = today_local - timedelta(days=1)
    targets = (yesterday_local, today_local)

    written = 0
    indices_written = 0
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        for d in targets:
            if daily.get(d) is None:
                continue
            indices_written += await _persist_day(
                repo,
                farm_id=farm_id,
                daily=daily,
                radwind_by_date=radwind_by_date,
                day=d,
            )
            written += 1

    return {
        "farm_id": str(farm_id),
        "status": "succeeded",
        "days_written": written,
        "indices_written": indices_written,
    }


# --- backfill_weather_indices ----------------------------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.backfill_weather_indices",
    bind=False,
    ignore_result=True,
)
def backfill_weather_indices(
    farm_id: str, tenant_schema: str, days: int = _BACKFILL_WINDOW_DAYS
) -> dict[str, Any]:
    """Reproject a wide window of history into `weather_index_daily`.

    The regular ingest only refreshes today + yesterday; this seeds the
    deeper history the climatology sweep needs (run after a bulk weather
    backfill has loaded the underlying observations).
    """
    return _run_task(_backfill_weather_indices_async(UUID(farm_id), tenant_schema, days))


async def _backfill_weather_indices_async(
    farm_id: UUID, tenant_schema: str, days: int
) -> dict[str, Any]:
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        centroid = await repo.get_farm_centroid(farm_id)
        if centroid is None:
            return {"farm_id": str(farm_id), "status": "farm_missing"}
        tz = tz_for_centroid(centroid["latitude"], centroid["longitude"])
        now_utc = datetime.now(UTC)
        obs_rows = await repo.read_observations(
            farm_id=farm_id,
            provider_code=None,
            since=now_utc - timedelta(days=days + 1),
            until=now_utc + timedelta(days=1),
        )

    daily, radwind_by_date = _aggregate_obs_window(obs_rows, tz)
    # Project every complete local day we have data for (skip "tomorrow",
    # which would be a partial all-None row).
    today_local = datetime.now(tz).date()
    targets = sorted(d for d in daily if d <= today_local)

    written = 0
    indices_written = 0
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        for d in targets:
            indices_written += await _persist_day(
                repo,
                farm_id=farm_id,
                daily=daily,
                radwind_by_date=radwind_by_date,
                day=d,
            )
            written += 1

    return {
        "farm_id": str(farm_id),
        "status": "succeeded",
        "days_written": written,
        "indices_written": indices_written,
    }


# --- backfill_weather (one-shot raw history) -------------------------------

# Chunk the archive fetch so one request + transaction stays bounded
# (~1 month of hourly rows) and progress is observable in logs.
_WEATHER_BACKFILL_CHUNK_DAYS = 31


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.backfill_weather",
    bind=False,
    ignore_result=True,
)
def backfill_weather(
    farm_id: str,
    tenant_schema: str,
    provider_code: str,
    start_iso: str,
    end_iso: str,
) -> dict[str, Any]:
    """Backfill raw hourly observations for [start, end] from the archive.

    ``start_iso``/``end_iso`` are ``YYYY-MM-DD`` (inclusive). Raw only — this
    does NOT chain derivations or index projection. Idempotent via the
    ``(time, farm_id, provider_code)`` unique constraint, so re-running is
    safe. Run ``weather.backfill_weather_indices`` afterwards to reproject
    the loaded history into ``weather_index_daily``.
    """
    return _run_task(
        _backfill_weather_async(
            UUID(farm_id),
            tenant_schema,
            provider_code,
            date.fromisoformat(start_iso),
            date.fromisoformat(end_iso),
        )
    )


async def _backfill_weather_async(
    farm_id: UUID,
    tenant_schema: str,
    provider_code: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    factory = AsyncSessionLocal()

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        centroid = await repo.get_farm_centroid(farm_id)
    if centroid is None:
        return {"farm_id": str(farm_id), "status": "farm_missing"}

    provider = _provider_factory(provider_code)
    total_inserted = 0
    total_fetched = 0
    chunks = 0
    try:
        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(
                chunk_start + timedelta(days=_WEATHER_BACKFILL_CHUNK_DAYS - 1), end_date
            )
            observations = await provider.fetch_archive(
                latitude=centroid["latitude"],
                longitude=centroid["longitude"],
                start_date=chunk_start,
                end_date=chunk_end,
            )
            async with factory() as session, session.begin():
                await _set_tenant_context(session, tenant_schema)
                repo = WeatherRepository(session)
                inserted = await repo.upsert_observations(
                    farm_id=farm_id,
                    provider_code=provider_code,
                    observations=observations,
                )
            total_inserted += inserted
            total_fetched += len(observations)
            chunks += 1
            _log.info(
                "weather_backfill_chunk",
                farm_id=str(farm_id),
                start=chunk_start.isoformat(),
                end=chunk_end.isoformat(),
                fetched=len(observations),
                inserted=inserted,
            )
            chunk_start = chunk_end + timedelta(days=1)
    finally:
        await provider.aclose()

    return {
        "farm_id": str(farm_id),
        "status": "succeeded",
        "chunks": chunks,
        "observations_fetched": total_fetched,
        "observations_inserted": total_inserted,
    }


# --- weather-index climatology baselines (PR-W3) ---------------------------


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.recompute_baselines_for_tenant",
    bind=False,
    ignore_result=True,
)
def recompute_weather_baselines_for_tenant(tenant_schema: str) -> dict[str, int]:
    """Recompute every (farm, index) climatology baseline in one tenant."""
    return _run_task(_recompute_weather_baselines_for_tenant_async(tenant_schema))


async def _recompute_weather_baselines_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        pairs = await repo.list_distinct_weather_index_pairs()

    baselines_written = 0
    deviations_updated = 0
    pairs_processed = 0
    for farm_id, index_code in pairs:
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            repo = WeatherRepository(session)
            history = await repo.read_weather_index_history(farm_id=farm_id, index_code=index_code)
            # day → naive datetime for the DOY/year math the pure helper does.
            rows = compute_block_baselines(
                (
                    HistoryRow(
                        time=datetime(r["date"].year, r["date"].month, r["date"].day),
                        mean=r["value"],
                    )
                    for r in history
                ),
                window_days=_WEATHER_BASELINE_WINDOW_DAYS,
            )
            for row in rows:
                await repo.upsert_weather_index_baseline(
                    farm_id=farm_id,
                    index_code=index_code,
                    day_of_year=row.day_of_year,
                    baseline_mean=row.baseline_mean,
                    baseline_std=row.baseline_std,
                    sample_count=row.sample_count,
                    window_days=_WEATHER_BASELINE_WINDOW_DAYS,
                    years_observed=row.years_observed,
                )
            # Re-derive the z-score on existing index rows so anomalies
            # light up without waiting for the next ingest of each day.
            deviations_updated += await repo.recompute_weather_index_deviations(
                farm_id=farm_id, index_code=index_code
            )
            baselines_written += len(rows)
            pairs_processed += 1

    _log.info(
        "weather_baselines_recomputed",
        tenant_schema=tenant_schema,
        pairs_processed=pairs_processed,
        baselines_written=baselines_written,
        deviations_updated=deviations_updated,
    )
    return {
        "pairs_processed": pairs_processed,
        "baselines_written": baselines_written,
        "deviations_updated": deviations_updated,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.recompute_baselines_sweep",
    bind=False,
    ignore_result=True,
)
def recompute_weather_baselines_sweep() -> dict[str, int]:
    """Beat sweep: walk every active tenant and queue per-tenant recomputes."""
    return _run_task(_recompute_weather_baselines_sweep_async())


async def _recompute_weather_baselines_sweep_async() -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            )
        ).all()
    schemas = [str(r[0]) for r in rows]

    enqueued = 0
    for schema in schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        recompute_weather_baselines_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}


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


# --- compute_weather_risk (Phase 2) ----------------------------------------

# Trailing daily window the risk accumulation models integrate over. Matches
# the registry's per-model default; one window serves all V1 mango models.
_RISK_WINDOW_DAYS = 14


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.compute_risk_for_tenant",
    bind=False,
    ignore_result=True,
)
def compute_weather_risk_for_tenant(tenant_schema: str) -> dict[str, Any]:
    """Score every active crop block in one tenant and upsert weather_risk_daily."""
    return _run_task(_compute_weather_risk_for_tenant_async(tenant_schema))


async def _compute_weather_risk_for_tenant_async(tenant_schema: str) -> dict[str, Any]:
    factory = AsyncSessionLocal()

    # Step 1: which blocks have a current crop, grouped by their farm.
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        repo = WeatherRepository(session)
        blocks = await repo.list_active_blocks_with_current_crop()

    by_farm: dict[UUID, list[dict[str, Any]]] = {}
    for b in blocks:
        by_farm.setdefault(b["farm_id"], []).append(b)

    rows_written = 0
    blocks_scored = 0
    for farm_id, farm_blocks in by_farm.items():
        # Step 2: one farm-centroid weather window, reused for all its blocks.
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            repo = WeatherRepository(session)
            centroid = await repo.get_farm_centroid(farm_id)
            if centroid is None:
                continue
            tz = tz_for_centroid(centroid["latitude"], centroid["longitude"])
            now_utc = datetime.now(UTC)
            obs_rows = await repo.read_observations(
                farm_id=farm_id,
                provider_code=None,
                since=now_utc - timedelta(days=_RISK_WINDOW_DAYS + 1),
                until=now_utc + timedelta(days=1),
            )

        daily, radwind_by_date = _aggregate_obs_window(obs_rows, tz)
        as_of = datetime.now(tz).date()
        window = build_risk_window(
            daily, radwind_by_date, as_of=as_of, window_days=_RISK_WINDOW_DAYS
        )
        if not window:
            continue

        # Step 3: score each block against the shared window + upsert.
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            repo = WeatherRepository(session)
            for b in farm_blocks:
                ctx = RiskBlockContext(
                    crop_path=b["crop_path"],
                    growth_stage=b["growth_stage"],
                    canopy_size_class=b["canopy_size_class"],
                )
                scores = evaluate_risks(window, ctx)
                if not scores:
                    continue
                for s in scores:
                    await repo.upsert_weather_risk_daily(
                        block_id=b["block_id"],
                        date=as_of,
                        risk_code=s.risk_code,
                        score=s.score,
                        level=s.level.value,
                        inputs=s.inputs,
                    )
                    rows_written += 1
                blocks_scored += 1

    _log.info(
        "weather_risk_computed",
        tenant_schema=tenant_schema,
        farms=len(by_farm),
        blocks_scored=blocks_scored,
        rows_written=rows_written,
    )
    return {
        "farms": len(by_farm),
        "blocks_scored": blocks_scored,
        "rows_written": rows_written,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="weather.compute_risk_daily_sweep",
    bind=False,
    ignore_result=True,
)
def compute_weather_risk_daily_sweep() -> dict[str, int]:
    """Beat sweep: walk every active tenant and queue per-tenant risk computes."""
    return _run_task(_compute_weather_risk_daily_sweep_async())


async def _compute_weather_risk_daily_sweep_async() -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            )
        ).all()
    schemas = [str(r[0]) for r in rows]

    enqueued = 0
    for schema in schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        compute_weather_risk_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
