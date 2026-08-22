"""A Celery task must not leave the engine pool bound to its dead loop.

The production failure this covers: four unrelated Beat tasks - two weather
tasks, the integration-health streak watcher and the provider probe - all
raising ``RuntimeError: ... got Future ... attached to a different loop`` on
every run. None of them was at fault. ``farms.farm_scope_consistency_check``
and ``iam.reconcile_keycloak`` called ``asyncio.run`` without disposing the
engine, so whichever task the worker picked up next inherited pooled asyncpg
connections belonging to a loop that had already closed.

The first two tests run the real engine against the real database. A mock
would not reproduce the failure, because the failure is entirely about which
event loop owns a socket.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from app.shared.db import session as session_mod
from app.shared.db.session import AsyncSessionLocal, dispose_engine, get_engine
from app.shared.db.task_runner import run_db_task

pytestmark = [pytest.mark.integration]


async def _touch_db() -> int:
    factory = AsyncSessionLocal()
    async with factory() as session:
        return int((await session.execute(text("SELECT 1"))).scalar_one())


async def _touch_then_return_engine() -> object:
    await _touch_db()
    return get_engine()


def test_two_sequential_task_runs_both_succeed() -> None:
    """Back-to-back task bodies, each in its own loop.

    Without the disposal in `run_db_task` the second call raises the
    different-loop error, which is exactly what production did.
    """
    assert run_db_task(_touch_db()) == 1
    assert run_db_task(_touch_db()) == 1
    assert run_db_task(_touch_db()) == 1


def test_a_leaked_engine_does_not_break_the_next_task() -> None:
    """The production shape, reproduced: somebody forgot to dispose.

    An engine built and connected on one loop, then left behind. The next
    task must not inherit it. Disposing the two known offenders removes
    today's instance; this is the check that keeps the next one from
    costing a whole worker process.
    """

    async def _leak() -> None:
        # Connects, so the pool holds a socket owned by this loop, then
        # returns without disposing - exactly what the two tasks did.
        await _touch_db()

    asyncio.run(_leak())

    assert run_db_task(_touch_db()) == 1
    assert run_db_task(_touch_db()) == 1


def test_run_db_task_clears_the_engine_between_runs() -> None:
    """The global must not survive the loop that built its pool."""
    first = run_db_task(_touch_then_return_engine())
    second = run_db_task(_touch_then_return_engine())
    assert first is not second


def test_dispose_clears_the_global_even_when_dispose_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing dispose must not leave the broken engine installed.

    Disposing a pool whose connections belong to a closed loop can itself
    raise. If the global survived that, every later task in the worker
    process would fail the same way for the life of the process - one bad
    task would take the worker down permanently rather than for one run.
    """

    class _BrokenEngine:
        async def dispose(self, close: bool = True) -> None:
            raise RuntimeError("pool is bound to a closed loop")

    broken: Any = _BrokenEngine()
    monkeypatch.setattr(session_mod, "_engine", broken, raising=False)

    with pytest.raises(RuntimeError):
        asyncio.run(dispose_engine())

    assert session_mod._engine is None
