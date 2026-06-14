"""Celery tasks for phenology auto-advance.

* ``phenology.advance_for_tenant(schema)`` — move every eligible block in
  one tenant to its calendar/age-derived stage (writes GrowthStageLog
  ``source='derived'``). Locked blocks are skipped; idempotent.
* ``phenology.advance_growth_stages`` — Beat-driven multi-tenant fan-out.

Cadence is set in ``workers/beat/main.py`` against
``phenology_advance_seconds`` (daily). The recommendation engine reads the
resulting ``growth_stage`` with no changes of its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
from app.modules.farms.service import get_farm_service
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
    name="phenology.advance_for_tenant",
    bind=False,
    ignore_result=True,
)
def advance_for_tenant(tenant_schema: str) -> dict[str, int]:
    return _run_task(_advance_for_tenant_async(tenant_schema))


async def _advance_for_tenant_async(tenant_schema: str) -> dict[str, int]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_tenant_context(session, tenant_schema)
        async with factory() as public_session:
            svc = get_farm_service(tenant_session=session, public_session=public_session)
            return await svc.advance_growth_stages(tenant_schema=tenant_schema)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="phenology.advance_growth_stages",
    bind=False,
    ignore_result=True,
)
def advance_growth_stages() -> dict[str, int]:
    return _run_task(_advance_sweep_async())


async def _advance_sweep_async() -> dict[str, int]:
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
        advance_for_tenant.delay(schema)
        enqueued += 1
    _log.info("phenology_advance_sweep_enqueued", tenants=len(schemas), enqueued=enqueued)
    return {"tenants_scanned": len(schemas), "enqueued": enqueued}
