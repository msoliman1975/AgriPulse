"""The verdict write, against a real database.

A fake repository has hidden two SQL bugs in this codebase before, so the
three statements in `VERDICT_SQL` are asserted here and not through a stub.
The behaviours that matter are the ones a single-pass test cannot see:

  * a second pass with the same answer must not open a new interval, or the
    replay reports that every block changed every night;
  * a changed answer must close and reopen at the same instant, or an as-of
    read lands in a gap where the block has no verdict at all;
  * a tree that produced nothing must lose its open verdict, or the block
    goes on claiming it was checked by a tree that no longer runs on it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]

_FARM = uuid4()

# One tenant schema for the whole module. Creating a tenant replays every
# tenant migration, and a schema per test is what pushed the integration job
# past its budget last time. Every test here uses its own block id, so the
# shared rows never meet.
_SHARED: dict[str, Any] = {}


async def _repo(admin_session: Any) -> RecommendationsRepository:
    if not _SHARED:
        slug = f"vw-{uuid4().hex[:8]}"
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"o@{slug}.test")
        await admin_session.commit()
        _SHARED["schema"] = str(tenant.schema_name)
    # Re-applied every time: `admin_session` is function-scoped, and a commit
    # anywhere drops the search_path with no error to say so.
    await admin_session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))
    return RecommendationsRepository(tenant_session=admin_session, public_session=admin_session)


def _row(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "farm_id": _FARM,
        "block_id": None,
        "cell_id": None,
        "scope": "block",
        "tree_id": None,
        "tree_code": "demo_v1",
        "tree_version": 1,
        "leaf_node_id": "leaf_ok",
        "kind": "status",
        "status_code": "good",
        "severity": None,
        "text_en": "Checked and fine.",
        "text_ar": None,
        "alert_id": None,
        "recommendation_id": None,
    }
    base.update(kw)
    return base


async def _rows(session: Any, block_id: UUID) -> list[dict[str, Any]]:
    result = await session.execute(
        text(
            """
            SELECT status_code, cell_id, tree_code, valid_from, valid_to,
                   last_evaluated_at, severity, alert_id
              FROM decision_tree_block_verdicts
             WHERE block_id = :b
             ORDER BY valid_from, status_code
            """
        ),
        {"b": str(block_id)},
    )
    return [dict(r) for r in result.mappings().all()]


@pytest.mark.asyncio
async def test_the_first_pass_opens_one_row_per_tree_and_cell(
    admin_session: Any,
) -> None:
    repo = await _repo(admin_session)
    block_id, tree_id = uuid4(), uuid4()
    cells = [uuid4(), uuid4()]
    at = datetime.now(UTC) - timedelta(days=3)

    counts = await repo.sync_verdicts(
        rows=[
            _row(block_id=block_id, tree_id=tree_id),
            *[_row(block_id=block_id, tree_id=tree_id, cell_id=c, scope="cell") for c in cells],
        ],
        run_id=None,
        at=at,
    )

    assert counts == {"confirmed": 0, "closed": 0, "opened": 3}
    assert len(await repo.list_open_verdicts(block_id=block_id)) == 3


@pytest.mark.asyncio
async def test_the_same_answer_again_opens_nothing(admin_session: Any) -> None:
    """The interval keeps its start; only the last-seen stamp moves."""
    repo = await _repo(admin_session)
    block_id, tree_id = uuid4(), uuid4()
    first = datetime.now(UTC) - timedelta(days=3)
    second = datetime.now(UTC) - timedelta(days=2)
    row = _row(block_id=block_id, tree_id=tree_id)

    await repo.sync_verdicts(rows=[row], run_id=None, at=first)
    counts = await repo.sync_verdicts(rows=[row], run_id=None, at=second)

    assert counts == {"confirmed": 1, "closed": 0, "opened": 0}
    (stored,) = await _rows(admin_session, block_id)
    assert stored["valid_from"] == first
    assert stored["last_evaluated_at"] == second
    assert stored["valid_to"] is None


@pytest.mark.asyncio
async def test_a_changed_answer_closes_and_reopens_at_one_instant(
    admin_session: Any,
) -> None:
    repo = await _repo(admin_session)
    block_id, tree_id = uuid4(), uuid4()
    first = datetime.now(UTC) - timedelta(days=2)
    second = datetime.now(UTC) - timedelta(days=1)

    await repo.sync_verdicts(rows=[_row(block_id=block_id, tree_id=tree_id)], run_id=None, at=first)
    counts = await repo.sync_verdicts(
        rows=[
            _row(
                block_id=block_id,
                tree_id=tree_id,
                status_code="issue",
                leaf_node_id="leaf_bad",
                text_en="Soil salinity is above the band.",
            )
        ],
        run_id=None,
        at=second,
    )

    assert counts == {"confirmed": 0, "closed": 1, "opened": 1}
    closed, opened = await _rows(admin_session, block_id)
    assert closed["status_code"] == "good"
    assert closed["valid_to"] == second
    assert opened["status_code"] == "issue"
    # No gap: the new interval starts exactly where the old one ended.
    assert opened["valid_from"] == closed["valid_to"]


@pytest.mark.asyncio
async def test_rewritten_wording_is_a_new_interval(admin_session: Any) -> None:
    """A republished leaf that keeps its status but rewrites its sentence.

    A reader looking at "good since Tuesday" should not be shown wording that
    only appeared today.
    """
    repo = await _repo(admin_session)
    block_id, tree_id = uuid4(), uuid4()
    at = datetime.now(UTC) - timedelta(days=1)

    await repo.sync_verdicts(rows=[_row(block_id=block_id, tree_id=tree_id)], run_id=None, at=at)
    counts = await repo.sync_verdicts(
        rows=[_row(block_id=block_id, tree_id=tree_id, text_en="Canopy is dense.")],
        run_id=None,
        at=datetime.now(UTC),
    )

    assert counts["closed"] == 1
    assert counts["opened"] == 1


@pytest.mark.asyncio
async def test_the_replay_reads_a_past_date(admin_session: Any) -> None:
    repo = await _repo(admin_session)
    block_id, tree_id = uuid4(), uuid4()
    three_days = datetime.now(UTC) - timedelta(days=3)
    yesterday = datetime.now(UTC) - timedelta(days=1)

    await repo.sync_verdicts(
        rows=[_row(block_id=block_id, tree_id=tree_id)], run_id=None, at=three_days
    )
    await repo.sync_verdicts(
        rows=[
            _row(
                block_id=block_id,
                tree_id=tree_id,
                status_code="issue",
                leaf_node_id="leaf_bad",
                text_en="Soil salinity is above the band.",
            )
        ],
        run_id=None,
        at=yesterday,
    )

    two_days_ago = datetime.now(UTC) - timedelta(days=2)
    result = await admin_session.execute(
        text(
            """
            SELECT status_code FROM decision_tree_block_verdicts
             WHERE block_id = :b
               AND valid_from <= :at AND (valid_to IS NULL OR valid_to > :at)
            """
        ),
        {"b": str(block_id), "at": two_days_ago},
    )

    assert result.scalars().all() == ["good"]


@pytest.mark.asyncio
async def test_a_tree_that_said_nothing_loses_its_verdict(admin_session: Any) -> None:
    """Targeting stopped matching, the farm turned it off, or it errored."""
    repo = await _repo(admin_session)
    block_id, gone, stays = uuid4(), uuid4(), uuid4()
    at = datetime.now(UTC) - timedelta(days=1)

    await repo.sync_verdicts(
        rows=[
            _row(block_id=block_id, tree_id=gone),
            _row(block_id=block_id, tree_id=stays, tree_code="pest_v1"),
        ],
        run_id=None,
        at=at,
    )
    closed = await repo.close_absent_verdicts(
        block_id=block_id, tree_ids=[stays], at=datetime.now(UTC)
    )

    assert closed == 1
    still_open = await repo.list_open_verdicts(block_id=block_id)
    assert [r["tree_code"] for r in still_open] == ["pest_v1"]


@pytest.mark.asyncio
async def test_a_cell_the_pass_never_reached_is_closed(admin_session: Any) -> None:
    """A rezone retires cells; the rows they left behind must not stay open."""
    repo = await _repo(admin_session)
    block_id, tree_id = uuid4(), uuid4()
    kept, retired = uuid4(), uuid4()
    at = datetime.now(UTC) - timedelta(days=1)

    await repo.sync_verdicts(
        rows=[
            _row(block_id=block_id, tree_id=tree_id),
            _row(block_id=block_id, tree_id=tree_id, cell_id=kept, scope="cell"),
            _row(block_id=block_id, tree_id=tree_id, cell_id=retired, scope="cell"),
        ],
        run_id=None,
        at=at,
    )
    closed = await repo.close_stale_cell_verdicts(
        block_id=block_id, tree_id=tree_id, seen_cell_ids=[kept], at=datetime.now(UTC)
    )

    assert closed == 1
    open_cells = [
        r["cell_id"] for r in await repo.list_open_verdicts(block_id=block_id) if r["cell_id"]
    ]
    assert open_cells == [kept]
    # The block-scoped row is not a cell and must survive the cell close.
    assert any(r["cell_id"] is None for r in await repo.list_open_verdicts(block_id=block_id))


@pytest.mark.asyncio
async def test_two_trees_on_one_block_do_not_collide(admin_session: Any) -> None:
    repo = await _repo(admin_session)
    block_id = uuid4()
    at = datetime.now(UTC)

    counts = await repo.sync_verdicts(
        rows=[
            _row(block_id=block_id, tree_id=uuid4()),
            _row(
                block_id=block_id,
                tree_id=uuid4(),
                tree_code="pest_v1",
                kind="alert",
                status_code="alert",
                severity="critical",
                text_en="Fruit fly pressure.",
                alert_id=uuid4(),
            ),
        ],
        run_id=None,
        at=at,
    )

    assert counts["opened"] == 2
    stored = await repo.list_open_verdicts(block_id=block_id)
    assert {r["status_code"] for r in stored} == {"good", "alert"}


@pytest.mark.asyncio
async def test_an_empty_pass_writes_nothing(admin_session: Any) -> None:
    repo = await _repo(admin_session)

    counts = await repo.sync_verdicts(rows=[], run_id=None, at=datetime.now(UTC))

    assert counts == {"confirmed": 0, "closed": 0, "opened": 0}
