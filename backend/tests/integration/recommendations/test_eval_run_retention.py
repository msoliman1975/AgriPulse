"""Retention for decision-tree evaluation lineage.

Two things are worth a real DB rather than a mock: that the cutoff is
measured the way the docstring claims, and that deleting a run actually
takes its traces with it. The second is the whole reason retention is
expressed as one number on the parent — if the cascade were ever dropped,
pruning would silently orphan every trace it was supposed to reclaim, and
the table would keep growing while the runs list looked pruned.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.recommendations.tasks import _prune_eval_runs_async
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_RETENTION_DAYS = 100


# One tenant for the whole module. Creating a tenant replays every tenant
# migration — seconds each in CI — and a schema per test here is what pushed
# the integration job past its 20-minute budget. Safe to share: the prune is
# tenant-wide by design, and each test seeds and asserts on its own run ids.
_SCHEMA: dict[str, str] = {}


async def _shared_schema(admin_session: Any) -> str:
    if "name" not in _SCHEMA:
        slug = f"prune-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        _SCHEMA["name"] = str(tenant.schema_name)
    schema = _SCHEMA["name"]
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    return schema


async def _seed_run_with_trace(session: Any, *, age_days: int) -> str:
    """A run started ``age_days`` ago, carrying one trace."""
    run_id = (
        await session.execute(
            text(
                """
                INSERT INTO decision_tree_eval_runs (kind, started_at)
                VALUES ('sweep', now() - make_interval(days => :age))
                RETURNING id
                """
            ),
            {"age": age_days},
        )
    ).scalar_one()
    await session.execute(
        text(
            """
            INSERT INTO decision_tree_eval_traces (
                run_id, farm_id, block_id, tree_id, tree_code,
                tree_version, scope, status
            ) VALUES (
                :run_id, gen_random_uuid(), gen_random_uuid(), gen_random_uuid(),
                'demo_v1', 1, 'block', 'clear'
            )
            """
        ),
        {"run_id": run_id},
    )
    return str(run_id)


async def _counts(session: Any, run_id: str) -> tuple[int, int]:
    runs = (
        await session.execute(
            text("SELECT count(*) FROM decision_tree_eval_runs WHERE id = :r"), {"r": run_id}
        )
    ).scalar_one()
    traces = (
        await session.execute(
            text("SELECT count(*) FROM decision_tree_eval_traces WHERE run_id = :r"),
            {"r": run_id},
        )
    ).scalar_one()
    return int(runs), int(traces)


@pytest.mark.asyncio
async def test_prune_drops_old_runs_with_their_traces_and_keeps_recent_ones(
    admin_session: Any,
) -> None:
    schema = await _shared_schema(admin_session)

    stale = await _seed_run_with_trace(admin_session, age_days=_RETENTION_DAYS + 1)
    fresh = await _seed_run_with_trace(admin_session, age_days=_RETENTION_DAYS - 1)
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))

    assert await _counts(admin_session, stale) == (1, 1)
    assert await _counts(admin_session, fresh) == (1, 1)

    await _prune_eval_runs_async(retention_days=_RETENTION_DAYS)

    # The prune runs on its own engine/transaction; drop this session's
    # snapshot so the assertions below see the committed deletes.
    await admin_session.rollback()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))

    # Gone, and the trace went with it via the run_id cascade — not by a
    # second DELETE this task never issues.
    assert await _counts(admin_session, stale) == (0, 0)
    assert await _counts(admin_session, fresh) == (1, 1)


@pytest.mark.asyncio
async def test_an_unfinished_run_is_still_prunable(admin_session: Any) -> None:
    """The cutoff reads ``started_at``, not ``finished_at``. A run whose
    worker died never gets a finish time, and keying retention off that
    column would make exactly the runs you least want to keep immortal."""
    schema = await _shared_schema(admin_session)

    stuck = await _seed_run_with_trace(admin_session, age_days=_RETENTION_DAYS + 5)
    await admin_session.execute(
        text("UPDATE decision_tree_eval_runs SET finished_at = NULL WHERE id = :r"),
        {"r": stuck},
    )
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))

    await _prune_eval_runs_async(retention_days=_RETENTION_DAYS)

    await admin_session.rollback()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    assert await _counts(admin_session, stuck) == (0, 0)


@pytest.mark.asyncio
async def test_prune_reports_what_it_scanned(admin_session: Any) -> None:
    schema = await _shared_schema(admin_session)
    await _seed_run_with_trace(admin_session, age_days=_RETENTION_DAYS + 2)
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))

    summary = await _prune_eval_runs_async(retention_days=_RETENTION_DAYS)

    # Other tenants share this database, so the totals are lower bounds —
    # asserting an exact count here would make the test order-dependent.
    assert summary["tenants_scanned"] >= 1
    assert summary["tenants_pruned"] >= 1
    assert summary["runs_deleted"] >= 1
