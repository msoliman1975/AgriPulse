"""Beat sweep for `public.platform_alerts`, plus the Celery failure hook.

Two entry points, and they exist for different reasons:

``platform_alerts.sweep``
    Recomputes every sweep-detectable problem from scratch, writes what it
    finds, and closes what it no longer sees. Because it is a full
    recompute, absence is meaningful: an alert the sweep did not raise this
    run is an alert whose cause has gone.

``_on_task_failure``
    A ``task_failure`` signal handler. Needed because the sweep can only
    read state that a task managed to write. A task that raises on its
    first query writes nothing at all - it leaves no attempt row, no job
    row, and no failed status anywhere for a sweep to find. Two such tasks
    had been failing on every run in production for an unknown length of
    time with nothing to show for it.

    This is also the reason ``task_error`` alerts are excluded from
    absence-based auto-resolve: nothing recomputes them, so "not seen this
    sweep" would close them a few minutes after they opened. They time out
    on ``platform_alert_task_quiet_hours`` instead.

Known gap, stated rather than papered over: a task killed by the OOM killer
never reaches this handler, because the process is gone. That shows up
instead as whatever the task failed to produce - a silent stream or a stuck
job - which the sweep does catch.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from celery.signals import task_failure
from sqlalchemy import text

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.platform_alerts.detectors import (
    DETECTORS,
    SWEEP_KINDS,
    Finding,
    Thresholds,
)
from app.modules.platform_alerts.repository import PlatformAlertsRepository
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)


def _run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


def _thresholds() -> Thresholds:
    s = get_settings()
    return Thresholds(
        weather_warn_hours=s.platform_alert_weather_warn_hours,
        weather_crit_hours=s.platform_alert_weather_crit_hours,
        optical_warn_hours=s.platform_alert_optical_warn_hours,
        optical_crit_hours=s.platform_alert_optical_crit_hours,
        thermal_warn_hours=s.platform_alert_thermal_warn_hours,
        thermal_crit_hours=s.platform_alert_thermal_crit_hours,
        peer_lag_hours=s.platform_alert_peer_lag_hours,
        stuck_job_hours=s.platform_alert_stuck_job_hours,
        streak_threshold=s.integration_failure_streak_threshold,
    )


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="platform_alerts.sweep",
    bind=False,
    ignore_result=True,
)
def sweep() -> dict[str, Any]:
    """Beat entry point. Returns counts so a manual run is readable."""
    return _run_async(run_sweep())


async def run_sweep() -> dict[str, Any]:
    """Walk every active tenant, write findings, close what is fixed.

    Shared by the Beat task and the admin `POST /sweep` route, so an
    operator can force a run and see the same numbers Beat would produce.
    """
    th = _thresholds()
    factory = AsyncSessionLocal()

    async with factory() as session:
        tenants = (
            await session.execute(
                text(
                    """
                    SELECT id, slug, name, schema_name
                      FROM public.tenants
                     WHERE status = 'active' AND deleted_at IS NULL
                     ORDER BY slug
                    """
                )
            )
        ).all()

    all_findings: list[tuple[Any, Finding]] = []
    tenants_failed = 0

    for t in tenants:
        try:
            schema = sanitize_tenant_schema(t.schema_name)
        except ValueError:
            continue
        try:
            findings = await _scan_tenant(schema=schema, tenant_key=str(t.id), th=th)
        except Exception:
            # One tenant's schema being mid-migration, or missing a table a
            # detector expects, must not cost us the alerts for every other
            # tenant. Each tenant already runs on its own session, so there
            # is no poisoned transaction to unwind here.
            tenants_failed += 1
            _log.exception("platform_alert_sweep_tenant_failed", tenant_id=str(t.id))
            continue
        all_findings.extend((t, f) for f in findings)

    # All writes happen here, in one public transaction, after every tenant
    # has been read. That ordering is what makes absence-based resolve safe:
    # a tenant that failed to scan contributes no keys, and if we resolved
    # per-tenant as we went, its live alerts would be closed as "fixed".
    seen_keys: list[str] = []
    async with factory() as session, session.begin():
        repo = PlatformAlertsRepository(session)
        for t, f in all_findings:
            seen_keys.append(f.alert_key)
            await repo.upsert(
                alert_key=f.alert_key,
                category=f.category,
                kind=f.kind,
                severity=f.severity,
                title=f.title,
                detail=f.detail,
                context=f.context,
                tenant_id=t.id,
                tenant_slug=t.slug,
                tenant_name=t.name,
                farm_id=f.farm_id,
                farm_name=f.farm_name,
            )

        if tenants_failed:
            # Do not auto-resolve when the read was incomplete. Closing
            # alerts on the strength of a scan that partly failed would
            # report problems as fixed that we simply did not look at.
            resolved = 0
        else:
            resolved = await repo.auto_resolve_absent(kinds=SWEEP_KINDS, seen_keys=seen_keys)
        resolved += await repo.auto_resolve_quiet(
            kind="task_error", quiet_hours=get_settings().platform_alert_task_quiet_hours
        )
        resolved += await repo.auto_resolve_missing_tenants()

    result = {
        "tenants_scanned": len(tenants),
        "tenants_failed": tenants_failed,
        "findings": len(all_findings),
        "resolved": resolved,
        "swept_at": datetime.now(UTC).isoformat(),
    }
    _log.info("platform_alert_sweep_done", **result)
    return result


async def _scan_tenant(*, schema: str, tenant_key: str, th: Thresholds) -> list[Finding]:
    """Run every detector against one tenant schema.

    The transaction is explicit even though every detector is read-only:
    `SET LOCAL` is scoped to a transaction block and degrades to a no-op
    with a warning outside one. Without it the detectors would run against
    the default search_path and read the wrong schema - or, worse, whatever
    schema the previous statement left behind.

    A single transaction also pins `now()` for the whole tenant scan, so the
    ages two detectors report about the same farm cannot disagree.
    """
    factory = AsyncSessionLocal()
    findings: list[Finding] = []
    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        for detector in DETECTORS:
            findings.extend(await detector(session, tenant_key=tenant_key, th=th))
    return findings


# --- Celery failure hook ---------------------------------------------------


@task_failure.connect  # type: ignore[misc,untyped-decorator,unused-ignore]
def _on_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    **kwargs: Any,
) -> None:
    """Open (or bump) a `task_error` alert for a task that raised.

    Wrapped end to end in a bare except. Alerting is observability, and
    observability that can fail the thing it observes is worse than none -
    a broken alert write must never turn a retryable task failure into a
    second, different failure.
    """
    try:
        task_name = getattr(sender, "name", None) or str(sender)
        # The sweep's own failures would recurse straight back into here.
        if task_name == "platform_alerts.sweep":
            return
        exc_type = type(exception).__name__ if exception is not None else "UnknownError"
        message = str(exception)[:1000] if exception is not None else ""
        _run_async(_record_task_failure(task_name, exc_type, message, task_id))
    except Exception:  # alerting must never break the task it observes
        _log.warning("platform_alert_task_hook_failed", exc_info=True)


async def _record_task_failure(
    task_name: str, exc_type: str, message: str, task_id: str | None
) -> None:
    """Dedup key is (task, exception class), not the message.

    One broken query raises the same class with a slightly different message
    per tenant; keying on the message would open a card per tenant per run
    for what is one bug in one line of SQL. `occurrences` carries the volume
    instead.
    """
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await PlatformAlertsRepository(session).upsert(
            alert_key=f"task_error:{task_name}:{exc_type}",
            category="task",
            kind="task_error",
            severity="critical",
            title=f"Background task failing: {task_name}",
            detail=f"{exc_type}: {message}",
            context={
                "task_name": task_name,
                "exception_type": exc_type,
                "message": message,
                "last_task_id": task_id,
                "last_failed_at": datetime.now(UTC).isoformat(),
            },
        )
