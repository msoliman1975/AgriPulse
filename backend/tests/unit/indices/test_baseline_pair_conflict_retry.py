"""One deadlocked pair must not end the baseline sweep.

On 2026-08-22 production ran `indices.recompute_baselines_for_tenant` while
the TimescaleDB columnstore policy was converting a chunk of
`block_index_aggregates`. The two deadlocked, Postgres killed the sweep's
transaction, and the exception escaped `_recompute_pairs`. The tenant has 828
pairs and the run takes about 420 seconds, so every pair after the losing one
was skipped for that hour.

`_recompute_pairs` already opens one transaction per pair, and its docstring
already promised that one bad pair cannot lose the run. These tests pin the
part that makes that promise true.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.modules.indices import tasks as indices_tasks


class _FakeOrig(Exception):
    """Stands in for the driver error SQLAlchemy wraps.

    Only `sqlstate` matters: `_is_retryable_conflict` reads the code rather
    than the class, because the production failure arrived as an
    `asyncpg.exceptions.DeadlockDetectedError` wrapped in a
    `sqlalchemy.dialects.postgresql.asyncpg.Error` wrapped in a `DBAPIError`.
    """

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _dbapi_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("UPDATE block_index_aggregates ...", {}, _FakeOrig(sqlstate))


class _Service:
    """Records calls and raises whatever the script for this pair says."""

    def __init__(self, script: dict[str, list[BaseException | None]]) -> None:
        self._script = script
        self.calls: list[str] = []

    async def recompute_block_index_baselines(self, *, block_id: Any, index_code: str) -> int:
        self.calls.append(index_code)
        queue = self._script.get(index_code, [])
        outcome = queue.pop(0) if queue else None
        if outcome is not None:
            raise outcome
        return 1

    async def recompute_block_index_deviations(self, *, block_id: Any, index_code: str) -> int:
        return 2


class _Session:
    async def execute(self, *_: Any, **__: Any) -> None:
        return None

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    def begin(self) -> _Session:
        return self


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Swap the session factory, the service and the sleep for fakes.

    The SQL itself is not under test here; the loop's control flow is.
    """

    def _apply(script: dict[str, list[BaseException | None]]) -> _Service:
        service = _Service(script)
        monkeypatch.setattr(indices_tasks, "AsyncSessionLocal", lambda: (lambda: _Session()))
        monkeypatch.setattr(indices_tasks, "get_indices_service", lambda *, tenant_session: service)

        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr(indices_tasks.asyncio, "sleep", _no_sleep)
        return service

    return _apply


@pytest.mark.asyncio
async def test_a_deadlocked_pair_is_retried_and_then_succeeds(patched: Any) -> None:
    """40P01 is what the production failure carried. Re-running the pair is
    the documented cure, and the statement is safe to run more than once."""
    block = uuid4()
    service = patched({"ndvi": [_dbapi_error("40P01"), None]})

    counts = await indices_tasks._recompute_pairs("tenant_x", ((block, "ndvi"),))

    assert service.calls == ["ndvi", "ndvi"], "the pair should be attempted twice"
    assert counts["pairs_processed"] == 1
    assert counts["pairs_failed"] == 0
    assert counts["conflict_retries"] == 1
    assert counts["baselines_written"] == 1


@pytest.mark.asyncio
async def test_a_pair_that_keeps_deadlocking_costs_only_that_pair(patched: Any) -> None:
    """The bug this file exists for. Before the fix the second pair was never
    reached, and on production that meant hundreds of pairs skipped."""
    first, second = uuid4(), uuid4()
    service = patched({"ndvi": [_dbapi_error("40P01")] * indices_tasks._PAIR_ATTEMPTS})

    counts = await indices_tasks._recompute_pairs("tenant_x", ((first, "ndvi"), (second, "ndmi")))

    assert service.calls == ["ndvi"] * indices_tasks._PAIR_ATTEMPTS + ["ndmi"]
    assert counts["pairs_processed"] == 1, "the second pair must still run"
    assert counts["pairs_failed"] == 1
    assert counts["baselines_written"] == 1


@pytest.mark.asyncio
async def test_a_non_conflict_error_is_not_retried(patched: Any) -> None:
    """A missing column will not fix itself on a second attempt. Retrying it
    would triple the time a broken sweep takes to finish."""
    block = uuid4()
    service = patched({"ndvi": [_dbapi_error("42703")]})

    counts = await indices_tasks._recompute_pairs("tenant_x", ((block, "ndvi"),))

    assert service.calls == ["ndvi"], "one attempt only"
    assert counts["pairs_failed"] == 1
    assert counts["conflict_retries"] == 0


@pytest.mark.asyncio
async def test_a_plain_exception_still_lets_the_run_continue(patched: Any) -> None:
    """Not every failure arrives as a DBAPIError."""
    first, second = uuid4(), uuid4()
    patched({"ndvi": [ValueError("boom")]})

    counts = await indices_tasks._recompute_pairs("tenant_x", ((first, "ndvi"), (second, "ndmi")))

    assert counts["pairs_processed"] == 1
    assert counts["pairs_failed"] == 1
