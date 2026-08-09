"""Trace list queries — every filter combination must actually execute.

`list_eval_traces` builds its WHERE clause from whichever filters are set.
The bound parameters have to be declared in lock-step with those clauses:
``text().bindparams()`` raises ``ArgumentError`` for a parameter the
statement never mentions, so declaring all of them up front makes every
call that omits one fail with a 500 — which is exactly what shipped and
what the first real query against a local database found.

A test that only exercises the all-filters-set path would not have caught
it. These run each filter alone, and none at all.

**One tenant schema for the whole module.** Creating a tenant replays every
tenant migration, which is seconds each in CI; a schema per test here is
what pushed the integration job past its 20-minute budget. The seeded rows
are therefore shared, so assertions look for the seeded traces rather than
asserting the table's exact size — the unfiltered query legitimately sees
whatever else the module put there.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_TREE_CODE = "trace_query_demo_v1"

# Populated by the first test to ask for it; reused by every test after.
_SHARED: dict[str, Any] = {}


async def _shared_fixture(admin_session: Any) -> tuple[RecommendationsRepository, dict[str, Any]]:
    """One tenant, one run, three traces — created once for the module.

    Returns a repository bound to ``admin_session`` (which is function-scoped,
    so it cannot be cached) plus the ids of the seeded rows.
    """
    if not _SHARED:
        slug = f"tq-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))

        run_id = (
            await admin_session.execute(
                text("INSERT INTO decision_tree_eval_runs (kind) VALUES ('sweep') RETURNING id")
            )
        ).scalar_one()
        farm_id, block_id = uuid4(), uuid4()
        for status, skip_axis in (("fired", None), ("clear", None), ("skipped", "country")):
            await admin_session.execute(
                text(
                    """
                    INSERT INTO decision_tree_eval_traces (
                        run_id, farm_id, block_id, tree_id, tree_code,
                        tree_version, scope, status, skip_axis, skip_detail
                    ) VALUES (
                        :run_id, :farm_id, :block_id, gen_random_uuid(),
                        :tree_code, 1, 'block', :status, :skip_axis,
                        CAST(:skip_detail AS jsonb)
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "farm_id": farm_id,
                    "block_id": block_id,
                    "tree_code": _TREE_CODE,
                    "status": status,
                    "skip_axis": skip_axis,
                    "skip_detail": '{"required": ["EG"], "actual": null}',
                },
            )
        await admin_session.commit()
        _SHARED.update(
            schema=str(tenant.schema_name),
            run_id=run_id,
            farm_id=farm_id,
            block_id=block_id,
        )

    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    repo = RecommendationsRepository(tenant_session=admin_session, public_session=admin_session)
    return repo, _SHARED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_name",
    ["none", "run_id", "block_id", "farm_id", "tree_code", "status", "all"],
)
async def test_every_filter_combination_executes(admin_session: Any, filter_name: str) -> None:
    repo, seeded = await _shared_fixture(admin_session)

    kwargs: dict[str, Any] = {}
    if filter_name in ("run_id", "all"):
        kwargs["run_id"] = seeded["run_id"]
    if filter_name in ("block_id", "all"):
        kwargs["block_id"] = seeded["block_id"]
    if filter_name in ("farm_id", "all"):
        kwargs["farm_id"] = seeded["farm_id"]
    if filter_name in ("tree_code", "all"):
        kwargs["tree_code"] = _TREE_CODE
    if filter_name in ("status", "all"):
        kwargs["status_filter"] = ("fired", "clear", "skipped")

    rows = await repo.list_eval_traces(**kwargs)

    # The query executing at all is the regression under test; that it also
    # returns the seeded rows proves the clause was applied, not dropped.
    ours = [r for r in rows if r["run_id"] == seeded["run_id"]]
    assert len(ours) == 3, f"{filter_name}: expected the 3 seeded traces, got {len(ours)}"
    assert {r["status"] for r in ours} == {"fired", "clear", "skipped"}


@pytest.mark.asyncio
async def test_status_filter_narrows(admin_session: Any) -> None:
    repo, seeded = await _shared_fixture(admin_session)

    rows = await repo.list_eval_traces(run_id=seeded["run_id"], status_filter=("skipped",))

    assert len(rows) == 1
    (row,) = rows
    assert row["status"] == "skipped"
    assert row["skip_axis"] == "country"
    # `actual: null` is the unset case — the whole reason skip_detail exists.
    assert row["skip_detail"] == {"required": ["EG"], "actual": None}


@pytest.mark.asyncio
async def test_grid_cell_labels_reaches_the_block_through_its_grid_config(
    admin_session: Any,
) -> None:
    """``grid_cells`` has no ``block_id`` — a cell belongs to a grid *config*,
    and the config belongs to the block. Filtering the cell table directly is
    a column that does not exist, which only surfaces when the cell-scoped
    dry-run actually runs against a database.

    Asserts the query executes and scopes correctly, not that a particular
    grid exists: an ungridded block legitimately returns nothing.
    """
    repo, _ = await _shared_fixture(admin_session)

    labels = await repo.get_grid_cell_labels(block_id=uuid4())

    assert labels == {}


@pytest.mark.asyncio
async def test_a_run_that_matches_nothing_returns_nothing_rather_than_everything(
    admin_session: Any,
) -> None:
    """A filter that matches no rows must narrow to empty. A clause silently
    dropped from the WHERE would return the whole table instead."""
    repo, _ = await _shared_fixture(admin_session)

    rows = await repo.list_eval_traces(run_id=UUID(int=0))

    assert rows == []
