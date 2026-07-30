"""Celery task for purges too large to run in the request.

A purge that deletes thousands of R2 objects serially is well past the point
where a browser should be holding the connection open, so
``PurgeService.submit`` queues anything over the inline thresholds here and the
UI polls ``GET /admin/purge/jobs/{id}``.

The task is a thin wrapper: all the logic, phase recording and receipt writing
lives in :func:`app.modules.purge.service.run_job`, so the inline and queued
paths are the same code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from celery import shared_task

from app.core.logging import get_logger
from app.shared.db.session import dispose_engine

_log = get_logger(__name__)


def _run_task[T](coro: Coroutine[Any, Any, T]) -> T:
    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())


@shared_task(name="purge.run_job", ignore_result=True)  # type: ignore[misc,untyped-decorator,unused-ignore]
def run_purge_job(*, job_id: str) -> None:
    """Execute a queued purge job.

    No retry. A purge is not idempotent in the way a fetch is — a retry after a
    partial failure would re-run phases that already committed and inflate the
    receipt's counts. Failures land on the job row with the error, and the UI
    offers an explicit retry that re-plans from the current state.
    """
    from uuid import UUID

    from app.modules.purge.service import run_job

    _log.info("purge_job_started", job_id=job_id)
    _run_task(run_job(UUID(job_id)))
    _log.info("purge_job_finished", job_id=job_id)
