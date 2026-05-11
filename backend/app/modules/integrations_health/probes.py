"""Periodic provider-probe scheduler (PR-IH5).

Runs on Celery Beat. Walks every active provider in
`public.weather_providers` and `public.imagery_providers` and calls
their `probe()` method. Each result is written to
`public.provider_probe_results` for the Providers tab to read.

Probes are global — providers serve every tenant. The probe task uses
the public-schema engine session; no tenant context is set.

Pruning: each task invocation also deletes probe rows older than 7
days. That keeps the table bounded without a separate retention job.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.shared.db.ids import uuid7
from app.shared.db.session import AsyncSessionLocal, dispose_engine

_log = get_logger(__name__)

# Retention — see module docstring. Configurable later via
# platform_defaults if needed.
_PROBE_RETENTION_DAYS = 7


def _run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="integrations_health.probe_providers",
    bind=False,
    ignore_result=True,
)
def probe_providers() -> dict[str, Any]:
    """Beat entry point. Probes every active provider and records results."""
    return _run_async(_probe_providers_async())


async def _probe_providers_async() -> dict[str, Any]:
    factory = AsyncSessionLocal()

    # Step 1: discover active provider catalogs from public.
    async with factory() as session:
        weather_rows = (
            await session.execute(
                text(
                    """
                    SELECT code FROM public.weather_providers
                    WHERE is_active = TRUE AND deleted_at IS NULL
                    """
                )
            )
        ).all()
        imagery_rows = (
            await session.execute(
                text(
                    """
                    SELECT code FROM public.imagery_providers
                    WHERE is_active = TRUE AND deleted_at IS NULL
                    """
                )
            )
        ).all()

    weather_codes = [r.code for r in weather_rows]
    imagery_codes = [r.code for r in imagery_rows]

    # Step 2: run probes. Sequentially per kind — provider count is small
    # and a fan-out gather() complicates error attribution. If this ever
    # becomes a perf concern, asyncio.gather over per-kind lists is the
    # one-line upgrade.
    probed: list[dict[str, Any]] = []
    for code in weather_codes:
        result = await _probe_weather(code)
        probed.append({"kind": "weather", "code": code, **result})
    for code in imagery_codes:
        result = await _probe_imagery(code)
        probed.append({"kind": "imagery", "code": code, **result})

    # Step 3: write results + prune retention window.
    async with factory() as session, session.begin():
        for row in probed:
            await session.execute(
                text(
                    """
                    INSERT INTO public.provider_probe_results
                    (id, provider_kind, provider_code, status,
                     latency_ms, error_message)
                    VALUES (:id, :kind, :code, :status,
                            :latency_ms, :error_message)
                    """
                ),
                {
                    "id": _new_id(),
                    "kind": row["kind"],
                    "code": row["code"],
                    "status": row["status"],
                    "latency_ms": row.get("latency_ms"),
                    "error_message": _truncate(row.get("error_message")),
                },
            )
        await session.execute(
            text(
                """
                DELETE FROM public.provider_probe_results
                WHERE probe_at < now() - make_interval(days => :days)
                """
            ),
            {"days": _PROBE_RETENTION_DAYS},
        )

    return {"probed": len(probed)}


async def _probe_weather(code: str) -> dict[str, Any]:
    """Construct an adapter, call probe(), normalize the result.

    Catches every exception so a misbehaving provider can't crash the
    scheduler — the resulting `error` status surfaces in the UI.
    """
    # Local import keeps a tight dependency graph: the scheduler module
    # does not import every provider module at module-import time, which
    # matters for Celery workers that may not have all adapter creds.
    from app.modules.weather.providers.open_meteo import OpenMeteoProvider
    from app.modules.weather.providers.protocol import ProbeResult

    provider: Any
    try:
        if code == "open_meteo":
            provider = OpenMeteoProvider()
        else:
            return {
                "status": "error",
                "latency_ms": None,
                "error_message": f"unknown weather provider: {code}",
            }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "latency_ms": None, "error_message": str(exc)}

    try:
        result: ProbeResult = await provider.probe()
        return {
            "status": result.status,
            "latency_ms": result.latency_ms,
            "error_message": result.error_message,
        }
    except Exception as exc:  # noqa: BLE001
        _log.exception("weather_probe_failed", provider_code=code)
        return {"status": "error", "latency_ms": None, "error_message": str(exc)}
    finally:
        try:
            await provider.aclose()
        except Exception:  # noqa: BLE001
            pass


async def _probe_imagery(code: str) -> dict[str, Any]:
    from app.modules.imagery.errors import SentinelHubNotConfiguredError
    from app.modules.imagery.providers.protocol import ProbeResult
    from app.modules.imagery.providers.sentinel_hub import SentinelHubProvider

    provider: Any
    try:
        if code == "sentinel_hub":
            provider = SentinelHubProvider()
        else:
            return {
                "status": "error",
                "latency_ms": None,
                "error_message": f"unknown imagery provider: {code}",
            }
    except SentinelHubNotConfiguredError as exc:
        # Not a transport failure — credentials simply aren't wired up
        # in this environment. Surfacing it as error gives the UI a
        # clear "configure me" hint instead of silently hiding the row.
        return {
            "status": "error",
            "latency_ms": None,
            "error_message": "provider not configured",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "latency_ms": None, "error_message": str(exc)}

    try:
        result: ProbeResult = await provider.probe()
        return {
            "status": result.status,
            "latency_ms": result.latency_ms,
            "error_message": result.error_message,
        }
    except Exception as exc:  # noqa: BLE001
        _log.exception("imagery_probe_failed", provider_code=code)
        return {"status": "error", "latency_ms": None, "error_message": str(exc)}
    finally:
        try:
            await provider.aclose()
        except Exception:  # noqa: BLE001
            pass


def _new_id() -> UUID:
    return uuid7()


def _truncate(s: str | None, limit: int = 1000) -> str | None:
    if s is None:
        return None
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."
