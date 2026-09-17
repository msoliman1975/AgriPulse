"""Celery task for the estate dry run.

One task: ``recommendations.estate_dry_run``. It folds one beta tree over one
tenant's active blocks and stores one report row.

**Why a task and not a request.** A cell-scoped tree over a 36-block tenant
with 121-cell grids is about 4,400 folds, each preceded by a per-block data
load. That is minutes, and a request held open for minutes is a request the
proxy closes before the report exists. The route inserts the ``running`` row,
returns its id, and this task fills it in.

**No Beat entry, deliberately.** A dry run is started by a person who is about
to read the report. Nothing schedules it. Design section 9 puts the estate run
in stage B, before a tenant is switched on, and the sweep itself is stage C.

**It writes nothing but its own report row.** The fold underneath is
``FoldingTreeAuthorService.dry_run``, which opens no recommendation, closes
none, and writes no trace. An integration test counts the rows in
``recommendations`` and ``alerts`` before and after, because that contract is
the reason the estate run is safe to point at a live tenant.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import text

from app.core.logging import get_logger
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
    """Point one session at one tenant's schema.

    The same two statements ``recommendations.tasks`` runs. Repeated here
    rather than imported so this module does not depend on the sweep's task
    file, which is another session's.
    """
    safe = sanitize_tenant_schema(tenant_schema)
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
        {"v": safe},
    )


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="recommendations.estate_dry_run",
    bind=False,
)
def estate_dry_run(
    tenant_schema: str,
    tenant_id: str,
    tree_id: str,
    run_id: str,
    author_tenant_id: str | None = None,
    block_limit: int | None = None,
) -> dict[str, Any]:
    """``author_tenant_id`` is the scope that owns the tree, not the tenant run.

    A beta tree is either the platform's (``tenant_id IS NULL``) or one
    tenant's, and ``get_tree_by_id`` matches one scope or the other, never
    both. The run's tenant is whose blocks are folded and is a different
    question: a platform tree is folded over a tenant's estate, which is the
    normal case in stage B.
    """
    return _run_task(
        _estate_dry_run_async(
            tenant_schema=tenant_schema,
            tenant_id=UUID(tenant_id),
            tree_id=UUID(tree_id),
            run_id=UUID(run_id),
            author_tenant_id=UUID(author_tenant_id) if author_tenant_id else None,
            block_limit=block_limit,
        )
    )


async def _estate_dry_run_async(
    *,
    tenant_schema: str,
    tenant_id: UUID,
    tree_id: UUID,
    run_id: UUID,
    author_tenant_id: UUID | None,
    block_limit: int | None,
) -> dict[str, Any]:
    """Fold the estate, store the report, and never leave the row ``running``.

    A failure marks the row ``failed`` with the message. A row left at
    ``running`` for ever is the one outcome a reader cannot act on: it reads
    the same as a run still working.
    """
    from app.modules.recommendations.folding_authoring import (
        get_folding_tree_author_service,
    )
    from app.modules.recommendations.folding_report import (
        EstateDryRunRepository,
        get_estate_dry_run_service,
    )

    factory = AsyncSessionLocal()
    try:
        async with factory() as tenant_session, tenant_session.begin():
            await _set_tenant_context(tenant_session, tenant_schema)
            async with factory() as public_session:
                author = get_folding_tree_author_service(
                    public_session=public_session, tenant_id=author_tenant_id
                )
                service = get_estate_dry_run_service(
                    author_service=author,
                    tenant_session=tenant_session,
                    tenant_schema=tenant_schema,
                )
                report = await service.run(tree_id=tree_id, run_id=run_id, block_limit=block_limit)
    # The row must never stay `running`: that reads the same as a run still
    # working, and a reader cannot act on it.
    except Exception as exc:
        _log.exception(
            "estate_dry_run_failed",
            tenant_schema=tenant_schema,
            tree_id=str(tree_id),
            run_id=str(run_id),
        )
        async with factory() as session, session.begin():
            await _set_tenant_context(session, tenant_schema)
            await EstateDryRunRepository(tenant_session=session).fail_run(
                run_id=run_id, error=str(exc)
            )
        return {"run_id": str(run_id), "state": "failed", "error": str(exc)}

    _log.info(
        "estate_dry_run_done",
        tenant_schema=tenant_schema,
        tenant_id=str(tenant_id),
        tree_id=str(tree_id),
        run_id=str(run_id),
        cells_evaluated=report.get("cells_evaluated"),
        cells_errored=report.get("cells_errored"),
    )
    return {
        "run_id": str(run_id),
        "state": "done",
        "cells_evaluated": int(report.get("cells_evaluated") or 0),
        "cells_errored": int(report.get("cells_errored") or 0),
    }
