"""Celery tasks for the recommendations engine.

* ``recommendations.evaluate_for_tenant(schema)`` — walks every active
  block in one tenant and runs every active decision tree against the
  block's latest signals. Idempotent: partial UNIQUE on
  ``(block_id, tree_id) WHERE state='open'`` keeps re-runs from
  duplicating an already-open recommendation.
* ``recommendations.evaluate_sweep`` — Beat-driven multi-tenant fan-out.

Cadence is set in ``workers/beat/main.py`` against
``recommendations_evaluate_sweep_seconds``. Daily in production; hourly
in dev so a fresh signal turns into a recommendation within one Beat
cycle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.recommendations.service import get_recommendations_service
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
    name="recommendations.evaluate_for_tenant",
    bind=False,
    ignore_result=True,
)
def evaluate_for_tenant(tenant_schema: str) -> dict[str, int]:
    return _run_task(_evaluate_for_tenant_async(tenant_schema))


async def _evaluate_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    blocks: tuple[Any, ...] = ()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        async with factory() as public_session:
            svc = get_recommendations_service(tenant_session=session, public_session=public_session)
            blocks = await svc._repo.list_active_block_ids()

    blocks_processed = 0
    recommendations_opened = 0
    for block_id in blocks:
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            async with factory() as public_session:
                svc = get_recommendations_service(
                    tenant_session=session, public_session=public_session
                )
                summary = await svc.evaluate_block(
                    block_id=block_id,
                    actor_user_id=None,
                    tenant_schema=tenant_schema,
                )
        blocks_processed += 1
        recommendations_opened += summary.get("recommendations_opened", 0)

    _log.info(
        "recommendations_tenant_sweep_done",
        tenant_schema=tenant_schema,
        blocks_processed=blocks_processed,
        recommendations_opened=recommendations_opened,
    )
    return {
        "blocks_processed": blocks_processed,
        "recommendations_opened": recommendations_opened,
    }


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="recommendations.evaluate_sweep",
    bind=False,
    ignore_result=True,
)
def evaluate_sweep() -> dict[str, int]:
    return _run_task(_evaluate_sweep_async())


async def _evaluate_sweep_async() -> dict[str, int]:
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
        evaluate_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
