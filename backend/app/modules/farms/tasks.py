"""Celery tasks for the farms module.

Beat picks up `farms.farm_scope_consistency_check` from the schedule in
`workers/beat/main.py`. The task body is a thin shim that runs the
async service in a fresh event loop — Celery workers are sync, so we
own the loop here rather than letting an outer policy manage it.

Owning the loop also means owning the engine: ``run_task_async`` disposes
it when the task ends. Leaving it behind strands pooled asyncpg
connections on a loop that is already closed, and the next database task
in the same pool process is the one that fails.
"""

from __future__ import annotations

from celery import shared_task

from app.core.logging import get_logger
from app.modules.farms.consistency_check import run_farm_scope_consistency_check
from app.shared.db.session import run_task_async

_log = get_logger(__name__)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="farms.farm_scope_consistency_check",
    bind=False,
    ignore_result=True,
)
def farm_scope_consistency_check() -> dict[str, int]:
    """Run one consistency-check pass synchronously inside the worker."""
    summary = run_task_async(run_farm_scope_consistency_check())
    _log.info("farm_scope_consistency_check.summary", **summary)
    return summary
