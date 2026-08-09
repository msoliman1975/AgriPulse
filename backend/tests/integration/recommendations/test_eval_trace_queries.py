"""Trace list queries — every filter combination must actually execute.

`list_eval_traces` builds its WHERE clause from whichever filters are set.
The bound parameters have to be declared in lock-step with those clauses:
``text().bindparams()`` raises ``ArgumentError`` for a parameter the
statement never mentions, so declaring all of them up front makes every
call that omits one fail with a 500 — which is exactly what shipped and
what the first real query against a local database found.

A test that only exercises the all-filters-set path would not have caught
it. These run each filter alone, and none at all.
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


async def _tenant_repo(admin_session: Any, prefix: str) -> tuple[RecommendationsRepository, str]:
    slug = f"{prefix}-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
    await admin_session.commit()
    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
    repo = RecommendationsRepository(tenant_session=admin_session, public_session=admin_session)
    return repo, str(tenant.schema_name)


async def _seed(admin_session: Any) -> dict[str, Any]:
    """One run with three traces: a fired block trace, a clear cell trace and
    a trace skipped on the country axis."""
    run_id = (
        await admin_session.execute(
            text("INSERT INTO decision_tree_eval_runs (kind) VALUES ('sweep') RETURNING id")
        )
    ).scalar_one()
    farm_id, block_id = uuid4(), uuid4()
    rows = [
        {"status": "fired", "scope": "block", "cell_id": None, "skip_axis": None},
        {"status": "clear", "scope": "block", "cell_id": None, "skip_axis": None},
        {"status": "skipped", "scope": "block", "cell_id": None, "skip_axis": "country"},
    ]
    for row in rows:
        await admin_session.execute(
            text(
                """
                INSERT INTO decision_tree_eval_traces (
                    run_id, farm_id, block_id, cell_id, tree_id, tree_code,
                    tree_version, scope, status, skip_axis, skip_detail
                ) VALUES (
                    :run_id, :farm_id, :block_id, :cell_id, gen_random_uuid(),
                    :tree_code, 1, :scope, :status, :skip_axis,
                    CAST(:skip_detail AS jsonb)
                )
                """
            ),
            {
                "run_id": run_id,
                "farm_id": farm_id,
                "block_id": block_id,
                "tree_code": _TREE_CODE,
                "skip_detail": '{"required": ["EG"], "actual": null}',
                **row,
            },
        )
    return {"run_id": run_id, "farm_id": farm_id, "block_id": block_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_name",
    ["none", "run_id", "block_id", "farm_id", "tree_code", "status", "all"],
)
async def test_every_filter_combination_executes(admin_session: Any, filter_name: str) -> None:
    # Underscores are rejected by the tenants slug CHECK.
    repo, _ = await _tenant_repo(admin_session, f"tq{filter_name.replace('_', '')[:6]}")
    seeded = await _seed(admin_session)

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

    assert len(rows) == 3, f"{filter_name}: expected all 3 seeded traces, got {len(rows)}"
    assert {r["status"] for r in rows} == {"fired", "clear", "skipped"}
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_status_filter_narrows(admin_session: Any) -> None:
    repo, _ = await _tenant_repo(admin_session, "tqnarrow")
    seeded = await _seed(admin_session)

    rows = await repo.list_eval_traces(run_id=seeded["run_id"], status_filter=("skipped",))

    assert len(rows) == 1
    (row,) = rows
    assert row["status"] == "skipped"
    assert row["skip_axis"] == "country"
    # `actual: null` is the unset case — the whole reason skip_detail exists.
    assert row["skip_detail"] == {"required": ["EG"], "actual": None}
    await admin_session.rollback()


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
    repo, _ = await _tenant_repo(admin_session, "tqlabels")

    labels = await repo.get_grid_cell_labels(block_id=uuid4())

    assert labels == {}
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_a_run_from_another_filter_returns_nothing_rather_than_everything(
    admin_session: Any,
) -> None:
    """A filter that matches no rows must narrow to empty. A clause silently
    dropped from the WHERE would return the whole table instead."""
    repo, _ = await _tenant_repo(admin_session, "tqempty")
    await _seed(admin_session)

    rows = await repo.list_eval_traces(run_id=UUID(int=0))

    assert rows == []
    await admin_session.rollback()
