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


async def _seed_succeeded_farm_job(admin_session: Any, farm_env: dict[str, Any]) -> None:
    """One farm-AOI scene the indices backfill will find and re-dispatch.

    The farm path, not the block path: `imagery_ingestion_jobs` is keyed per
    block and cannot see a scene fetched for the whole farm.
    """
    schema = farm_env["schema"]
    product_id = (
        await admin_session.execute(
            text("SELECT id FROM public.imagery_products ORDER BY code LIMIT 1")
        )
    ).scalar_one()
    sub_id = uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_subscriptions "
            "(id, farm_id, product_id, is_active, fetch_farm_aoi) "
            "VALUES (:id, :farm, :product, TRUE, TRUE)"
        ),
        {"id": str(sub_id), "farm": str(farm_env["farm_id"]), "product": str(product_id)},
    )
    await admin_session.execute(
        text(
            "INSERT INTO imagery_farm_ingestion_jobs "
            "(id, subscription_id, farm_id, product_id, scene_id, scene_datetime, status) "
            "VALUES (:id, :sub, :farm, :product, 'S2-TEST-1', now() - INTERVAL '2 days', "
            "        'succeeded')"
        ),
        {
            "id": str(uuid4()),
            "sub": str(sub_id),
            "farm": str(farm_env["farm_id"]),
            "product": str(product_id),
        },
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()


@pytest.mark.asyncio
async def test_window_binds_as_an_iso_date(farm_env: dict[str, Any]) -> None:
    """The regression: this raised DataError for every window."""
    window_from = (date.today() - timedelta(days=900)).isoformat()
    # No stored scenes, so nothing is enqueued — the point is that the query
    # binds and the body returns instead of blowing up.
    result = await imagery_tasks._backfill_farm_indices_async(
        farm_env["farm_id"], farm_env["schema"], window_from, date.today().isoformat(), None
    )
    # Both shapes are reported separately: a cut-over farm carries both in
    # its history, and one combined number could not say which half ran.
    assert result == {"scenes_enqueued": 0, "farm_scenes_enqueued": 0}


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
    # Both shapes are reported separately: a cut-over farm carries both in
    # its history, and one combined number could not say which half ran.
    assert result == {"scenes_enqueued": 0, "farm_scenes_enqueued": 0}


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


@pytest.mark.asyncio
async def test_a_run_with_scenes_queues_the_farm_baseline_recompute(
    admin_session: Any, farm_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backfill must leave the z-scores correct without a manual step.

    `baseline_deviation` is derived by `record_aggregate_row` at write time,
    against the baselines that exist then. A backfill writes history whose
    baselines do not exist yet, so those rows land NULL and every decision
    tree reading `indices.<code>.baseline_deviation` gets nothing until
    something recomputes.
    """
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        imagery_tasks.recompute_baselines_for_farm,
        "apply_async",
        lambda **kw: sent.append(kw),
    )
    monkeypatch.setattr(imagery_tasks.compute_indices, "delay", lambda *a, **k: None)
    await _seed_succeeded_farm_job(admin_session, farm_env)

    result = await imagery_tasks._backfill_farm_indices_async(
        farm_env["farm_id"], farm_env["schema"], "2024-01-30", date.today().isoformat(), None
    )
    assert result["farm_scenes_enqueued"] == 1, result

    # Two shots: the first for the normal case, the second for a heavy queue
    # that is still draining. The task only dispatches, so there is no
    # completion signal to wait on instead.
    assert len(sent) == 2, sent
    assert all(kw["queue"] == "light" for kw in sent), sent
    assert all(kw["args"] == [str(farm_env["farm_id"]), farm_env["schema"]] for kw in sent), sent
    assert sent[0]["countdown"] < sent[1]["countdown"], sent


@pytest.mark.asyncio
async def test_a_run_with_no_scenes_queues_nothing(
    farm_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing dispatched means nothing to recompute."""
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        imagery_tasks.recompute_baselines_for_farm,
        "apply_async",
        lambda **kw: sent.append(kw),
    )

    result = await imagery_tasks._backfill_farm_indices_async(
        farm_env["farm_id"], farm_env["schema"], "2024-01-30", date.today().isoformat(), None
    )
    assert result == {"scenes_enqueued": 0, "farm_scenes_enqueued": 0}
    assert sent == []
