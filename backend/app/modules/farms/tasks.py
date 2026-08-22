"""Celery tasks for the farms module.

Beat picks up `farms.farm_scope_consistency_check` from the schedule in
`workers/beat/main.py`. The task body is a thin shim that runs the
async service in a fresh event loop — Celery workers are sync, so we
own the loop here rather than letting an outer policy manage it.

This used to call `asyncio.run` directly. The service reads the database,
so the pooled connections it left behind belonged to a loop that closed
with the task, and the next database-touching task in that worker process
raised "got Future attached to a different loop". `run_db_task` disposes
the engine before the loop goes away.
"""

from __future__ import annotations

from celery import shared_task

from app.core.logging import get_logger
from app.modules.farms.consistency_check import run_farm_scope_consistency_check
from app.shared.db.task_runner import run_db_task

_log = get_logger(__name__)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="farms.farm_scope_consistency_check",
    bind=False,
    ignore_result=True,
)
def farm_scope_consistency_check() -> dict[str, int]:
    """Run one consistency-check pass synchronously inside the worker."""
    summary = run_db_task(run_farm_scope_consistency_check())
    _log.info("farm_scope_consistency_check.summary", **summary)
    return summary
