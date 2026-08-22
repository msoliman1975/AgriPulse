"""One place to run an async task body from a synchronous Celery task.

Celery workers are synchronous, so every task body that touches the
database opens its own event loop with ``asyncio.run``. The engine, by
contrast, is process-wide. An asyncpg connection belongs to the loop that
created it, so a pooled connection left behind by one task is unusable by
the next one and raises::

    RuntimeError: Task <...> got Future <...> attached to a different loop

The fix is to dispose the engine before the loop closes, which is why
twelve modules each grew their own ``_run_task`` / ``_run_async`` wrapper.
Two tasks did not: ``farms.farm_scope_consistency_check`` and
``iam.reconcile_keycloak`` called ``asyncio.run`` directly. Both read the
database, so either one poisoned the pool for whatever task the worker
picked up next. In production that showed up as four unrelated Beat tasks
failing with the loop error and nothing pointing at the two that caused it.

New task bodies should call `run_db_task` rather than write a thirteenth
copy of the wrapper.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from app.shared.db.session import dispose_engine


def run_db_task[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run ``coro`` in a fresh event loop and dispose the engine on exit."""

    async def _runner() -> T:
        try:
            return await coro
        finally:
            await dispose_engine()

    return asyncio.run(_runner())
