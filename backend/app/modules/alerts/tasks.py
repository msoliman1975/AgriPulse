"""Celery tasks for the alerts engine.

Two tasks:

  * ``evaluate_alerts_for_tenant(tenant_schema)`` — walks every active
    block in the tenant and runs the engine against the latest signals.
    Idempotent: re-firing for a block that already has open alerts for
    the same rules is a no-op (partial UNIQUE on (block_id, rule_code)
    where status IN open/ack/snoozed).
  * ``evaluate_alerts_sweep`` — Beat-driven multi-tenant fan-out;
    enqueues one ``evaluate_alerts_for_tenant`` per active tenant.

Cadence is set in ``workers/beat/main.py`` against the
``alerts_evaluate_sweep_seconds`` setting. Hourly is fine in dev;
nightly in production keeps the sweep cheap.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.alerts.service import get_alerts_service
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


async def _set_tenant_context(session: Any, tenant_schema: str) -> None:
    safe = sanitize_tenant_schema(tenant_schema)
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
        {"v": safe},
    )


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="alerts.evaluate_alerts_for_tenant",
    bind=False,
    ignore_result=True,
)
def evaluate_alerts_for_tenant(tenant_schema: str) -> dict[str, int]:
    return _run_task(_evaluate_alerts_for_tenant_async(tenant_schema))


async def _evaluate_alerts_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    blocks: tuple[Any, ...] = ()

    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        # Public session for the rule catalog reads. We open it on the
        # same engine so connection-pool reuse is honoured.
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            # `_repo` is a service-internal attribute; tasks need it
            # for the cheap distinct-block-id query, so we accept the
            # private-attribute access here (matches the indices Beat
            # task pattern in PR-4).
            blocks = await svc._repo.list_active_block_ids()

    blocks_processed = 0
    alerts_opened = 0
    for block_id in blocks:
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            async with factory() as public_session:
                svc = get_alerts_service(tenant_session=session, public_session=public_session)
                summary = await svc.evaluate_block(
                    block_id=block_id,
                    actor_user_id=None,
                    tenant_schema=tenant_schema,
                )
        blocks_processed += 1
        alerts_opened += summary.get("alerts_opened", 0)

    _log.info(
        "alerts_tenant_sweep_done",
        tenant_schema=tenant_schema,
        blocks_processed=blocks_processed,
        alerts_opened=alerts_opened,
    )
    return {"blocks_processed": blocks_processed, "alerts_opened": alerts_opened}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="alerts.evaluate_alerts_sweep",
    bind=False,
    ignore_result=True,
)
def evaluate_alerts_sweep() -> dict[str, int]:
    return _run_task(_evaluate_alerts_sweep_async())


async def _evaluate_alerts_sweep_async() -> dict[str, int]:
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
        evaluate_alerts_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
