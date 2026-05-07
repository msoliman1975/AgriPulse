"""Celery tasks for the indices module.

Currently one task: a Beat-driven weekly sweep that recomputes
per-(block, index, day-of-year) baselines from the rolling history of
``block_index_aggregates``. The actual aggregate writes happen inside
imagery's ``compute_indices`` task; baselines are derived data that
trail behind by up to a week.

We keep the task off the heavy queue because the math is light —
loading a few thousand rows per (block, index) and computing means is
trivially cheap. CPU is not the constraint; what we care about is
not contending with the imagery acquisition flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.indices.service import get_indices_service
from app.shared.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    sanitize_tenant_schema,
)

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Same pattern as imagery/tasks.py: dispose the engine after each
    invocation so a fresh asyncpg pool gets bound to the next task's
    event loop."""

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
    name="indices.recompute_baselines_for_tenant",
    bind=False,
    ignore_result=True,
)
def recompute_baselines_for_tenant(tenant_schema: str) -> dict[str, int]:
    """Recompute every (block, index) baseline pair in one tenant."""
    return _run_task(_recompute_baselines_for_tenant_async(tenant_schema))


async def _recompute_baselines_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    pairs: tuple[Any, ...] = ()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        svc = get_indices_service(tenant_session=session)
        # Reach through to the repo for the cheap distinct query.
        pairs = await svc._repo.list_distinct_block_index_pairs()  # type: ignore[attr-defined]

    written_total = 0
    pairs_processed = 0
    for block_id, index_code in pairs:
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            svc = get_indices_service(tenant_session=session)
            written = await svc.recompute_block_index_baselines(
                block_id=block_id, index_code=index_code
            )
        written_total += written
        pairs_processed += 1

    _log.info(
        "indices_baselines_recomputed",
        tenant_schema=tenant_schema,
        pairs_processed=pairs_processed,
        baselines_written=written_total,
    )
    return {"pairs_processed": pairs_processed, "baselines_written": written_total}


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="indices.recompute_baselines_sweep",
    bind=False,
    ignore_result=True,
)
def recompute_baselines_sweep() -> dict[str, int]:
    """Beat sweep: walk every active tenant and queue per-tenant recomputes."""
    return _run_task(_recompute_baselines_sweep_async())


async def _recompute_baselines_sweep_async() -> dict[str, int]:
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
        recompute_baselines_for_tenant.delay(schema)
        enqueued += 1
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
