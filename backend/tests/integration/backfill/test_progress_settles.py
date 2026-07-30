"""A finished backfill run must actually settle into a terminal status.

Production symptom: a run whose data had fully loaded sat on ``running``
forever. ``progress`` held the task's counters but no ``state`` key, and
``_settle`` decides "is this source done?" by testing for exactly that key —
so the run never settled and, because of the one-run-per-farm unique index,
the farm stayed permanently locked against further runs.

Every write in ``backfill_progress`` is deliberately best-effort (it swallows
and logs), which is right for bookkeeping but means a broken statement is
invisible. These tests assert the observable outcome instead, so a swallowed
failure cannot pass.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.shared import backfill_progress as bp

pytestmark = [pytest.mark.integration]


async def _insert_run(session: Any, *, sources: dict[str, bool]) -> UUID:
    run_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO public.backfill_runs
              (id, tenant_id, tenant_schema, farm_id, kind, sources,
               window_from, window_to, status)
            VALUES (:id, :tid, 'tenant_deadbeef', :fid, 'backfill',
                    CAST(:sources AS jsonb), DATE '2026-07-28', DATE '2026-07-28',
                    'queued')
            """
        ),
        {
            "id": str(run_id),
            "tid": str(uuid4()),
            "fid": str(uuid4()),
            "sources": json.dumps(sources),
        },
    )
    await session.commit()
    return run_id


async def _read(session: Any, run_id: UUID) -> tuple[str, dict[str, Any]]:
    # Fresh transaction: backfill_progress writes on its own sync connection.
    await session.rollback()
    row = (
        await session.execute(
            text("SELECT status, progress FROM public.backfill_runs WHERE id = :i"),
            {"i": str(run_id)},
        )
    ).one()
    return row[0], row[1]


@pytest.mark.asyncio
async def test_single_source_run_settles_to_succeeded(admin_session: Any) -> None:
    """The regression: this stayed 'running' in production."""
    run_id = await _insert_run(admin_session, sources={"imagery": False, "weather": True})

    bp.mark_running(run_id)
    bp.finish(run_id, "weather", counters={"observations_fetched": 24, "status": "succeeded"})

    status, progress = await _read(admin_session, run_id)
    # The `state` marker is what _settle counts; without it the run hangs.
    assert progress["weather"]["state"] == "done", progress
    assert progress["weather"]["observations_fetched"] == 24, progress
    assert status == "succeeded", f"run did not settle: {status} {progress}"


@pytest.mark.asyncio
async def test_two_source_run_waits_for_both_then_settles(admin_session: Any) -> None:
    run_id = await _insert_run(admin_session, sources={"imagery": True, "weather": True})

    bp.mark_running(run_id)
    bp.finish(run_id, "weather", counters={"observations_fetched": 10})

    status, _ = await _read(admin_session, run_id)
    assert status == "running", "must not settle while imagery is still outstanding"

    bp.finish(run_id, "imagery", counters={"scenes": 3})
    status, progress = await _read(admin_session, run_id)
    assert status == "succeeded", f"{status} {progress}"


@pytest.mark.asyncio
async def test_failed_source_settles_the_run_as_failed(admin_session: Any) -> None:
    run_id = await _insert_run(admin_session, sources={"imagery": False, "weather": True})

    bp.mark_running(run_id)
    bp.finish(run_id, "weather", failed=True, error="provider exploded")

    status, progress = await _read(admin_session, run_id)
    assert progress["weather"]["state"] == "failed", progress
    assert progress["weather"]["error"] == "provider exploded", progress
    assert status == "failed", f"{status} {progress}"


@pytest.mark.asyncio
async def test_partial_when_one_of_two_sources_fails(admin_session: Any) -> None:
    run_id = await _insert_run(admin_session, sources={"imagery": True, "weather": True})

    bp.mark_running(run_id)
    bp.finish(run_id, "weather", counters={"observations_fetched": 10})
    bp.finish(run_id, "imagery", failed=True, error="cdse 500")

    status, progress = await _read(admin_session, run_id)
    assert status == "partial", f"{status} {progress}"
