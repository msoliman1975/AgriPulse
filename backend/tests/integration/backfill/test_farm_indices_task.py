"""`imagery.backfill_farm_indices` must run, and must report if it dies.

Two production failures, one symptom. The task bound its window as raw ISO
strings into `CAST(:x AS timestamptz)`, so asyncpg raised

    DataError: invalid input for query argument $2: '2024-01-30'
    (expected a datetime.date or datetime.datetime instance, got 'str')

on every single invocation. And because the task only reported to
`backfill_progress` on its success path, that crash was never recorded — the
run's imagery source stayed silent, `_settle` waited on it forever, and the
console showed "Queued" for a task that had died seconds after dispatch.

The Celery wrapper drives its own event loop via `asyncio.run` (and disposes
the global engine afterwards), so these tests exercise the async body
directly on the test loop, and cover the wrapper's error path by making the
body raise. Calling the wrapper for real from an async test deadlocks
against the session-scoped engine.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.imagery import tasks as imagery_tasks
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


@pytest.fixture
async def farm_env(admin_session: Any) -> dict[str, Any]:
    slug = f"idx-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    farm_id = uuid4()
    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) VALUES (:id, 'IX', 'IX', "
            "ST_GeomFromText('POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,"
            "31.2 30.0))', 4326))"
        ),
        {"id": str(farm_id)},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
    return {"schema": tenant.schema_name, "farm_id": farm_id, "tenant_id": tenant.tenant_id}


async def _insert_run(session: Any, sources: dict[str, bool]) -> UUID:
    run_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO public.backfill_runs
              (id, tenant_id, tenant_schema, farm_id, kind, sources,
               window_from, window_to, status)
            VALUES (:id, :tid, 'tenant_deadbeef', :fid, 'indices',
                    CAST(:s AS jsonb), DATE '2024-01-30', DATE '2026-07-30', 'queued')
            """
        ),
        {
            "id": str(run_id),
            "tid": str(uuid4()),
            "fid": str(uuid4()),
            "s": json.dumps(sources),
        },
    )
    await session.commit()
    return run_id


@pytest.mark.asyncio
async def test_window_binds_as_an_iso_date(farm_env: dict[str, Any]) -> None:
    """The regression: this raised DataError for every window."""
    window_from = (date.today() - timedelta(days=900)).isoformat()
    # No stored scenes, so nothing is enqueued — the point is that the query
    # binds and the body returns instead of blowing up.
    result = await imagery_tasks._backfill_farm_indices_async(
        farm_env["farm_id"], farm_env["schema"], window_from, date.today().isoformat(), None
    )
    assert result == {"scenes_enqueued": 0}


@pytest.mark.asyncio
async def test_window_also_accepts_a_full_iso_datetime(farm_env: dict[str, Any]) -> None:
    """scripts.backfill_history passes datetimes, not plain dates."""
    result = await imagery_tasks._backfill_farm_indices_async(
        farm_env["farm_id"],
        farm_env["schema"],
        "2024-01-30T00:00:00+00:00",
        "2026-07-30T00:00:00+00:00",
        None,
    )
    assert result == {"scenes_enqueued": 0}


@pytest.mark.asyncio
async def test_a_crashing_task_settles_its_source_instead_of_hanging(
    admin_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead task must report, or the run waits on it forever."""
    run_id = await _insert_run(admin_session, {"imagery": True, "weather": False})

    def _boom(coro: Any) -> Any:
        coro.close()  # we never await it; keep the loop quiet
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(imagery_tasks, "_run_task", _boom)

    with pytest.raises(RuntimeError):
        imagery_tasks.backfill_farm_indices(
            str(uuid4()), "tenant_deadbeef", "2024-01-30", "2026-07-30", str(run_id)
        )

    await admin_session.rollback()
    status, progress = (
        await admin_session.execute(
            text("SELECT status, progress FROM public.backfill_runs WHERE id = :i"),
            {"i": str(run_id)},
        )
    ).one()
    assert progress["imagery"]["state"] == "failed", progress
    assert "provider exploded" in progress["imagery"]["error"], progress
    # Single declared source and it failed -> the run settles as failed
    # rather than sitting on `running` for someone to notice hours later.
    assert status == "failed", f"{status} {progress}"


@pytest.mark.asyncio
async def test_scenes_fanout_also_settles_on_crash(
    admin_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same guard on the sibling fan-out task."""
    run_id = await _insert_run(admin_session, {"imagery": True, "weather": False})

    def _boom(coro: Any) -> Any:
        coro.close()
        raise RuntimeError("db gone")

    monkeypatch.setattr(imagery_tasks, "_run_task", _boom)

    with pytest.raises(RuntimeError):
        imagery_tasks.backfill_farm_scenes(
            str(uuid4()), "tenant_deadbeef", "2024-01-30", "2026-07-30", False, str(run_id)
        )

    await admin_session.rollback()
    status, progress = (
        await admin_session.execute(
            text("SELECT status, progress FROM public.backfill_runs WHERE id = :i"),
            {"i": str(run_id)},
        )
    ).one()
    assert progress["imagery"]["state"] == "failed", progress
    assert status == "failed", f"{status} {progress}"


def test_as_date_parses_both_shapes() -> None:
    assert imagery_tasks._as_date("2024-01-30") == date(2024, 1, 30)
    assert imagery_tasks._as_date("2024-01-30T12:34:56+00:00") == date(2024, 1, 30)
