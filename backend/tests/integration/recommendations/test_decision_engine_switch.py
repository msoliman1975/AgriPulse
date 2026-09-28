"""The platform switch between the old engine and the beta engine.

Three behaviours:

  * **One engine at a time.** Under 'old' a beta tree writes nothing; under
    'beta' a live tree writes nothing. The same block, the same readings,
    two passes.
  * **The close-out.** Flipping closes what the outgoing trees wrote: open
    recommendations expire with a history row naming ``engine_retired``,
    tree alerts resolve, and current verdicts end. Rows from other sources
    are left alone.
  * **A repeated flip is a no-op.** Nothing is closed twice.

Integration tests run one at a time, and each test here flips the switch
back to 'old' on the way out, so no other test sees the beta engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.engine_switch import (
    RETIRED_REASON,
    read_engine,
    switch_engine,
)
from app.shared.db.session import AsyncSessionLocal
from tests.integration.recommendations.test_folding_execution import (
    _evaluate,
    _folding_compiled,
    _install_tree,
    _old_style_compiled,
    _seed_farm_and_block,
    _tenant_for,
    _write_index,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("_engine_restored")]


async def _flip(to: str) -> dict[str, Any]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL search_path TO public"))
        return await switch_engine(session, to=to, actor_user_id=None)  # type: ignore[arg-type]


@pytest.fixture
async def _engine_restored() -> AsyncIterator[None]:
    """Whatever a test does, the next test starts on the old engine."""
    await _flip("old")
    yield
    await _flip("old")


async def _set_beta(session: AsyncSession, tree_id: UUID) -> None:
    await session.execute(text("SET LOCAL search_path TO public"))
    await session.execute(
        text("UPDATE public.decision_trees SET stage = 'beta' WHERE id = :id").bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True))
        ),
        {"id": tree_id},
    )
    await session.commit()


async def _two_trees(admin_session: AsyncSession, suffix: str) -> tuple[UUID, str, UUID, str]:
    """A live old-style tree and a beta folding tree. Codes are unique per test."""
    live_code = f"eng_live_{suffix}"
    beta_code = f"eng_beta_{suffix}"
    live_id = await _install_tree(admin_session, compiled=_old_style_compiled(live_code))
    beta_id = await _install_tree(admin_session, compiled=_folding_compiled(beta_code))
    await _set_beta(admin_session, beta_id)
    return live_id, live_code, beta_id, beta_code


async def _dry_block(admin_session: AsyncSession, schema: str, suffix: str) -> tuple[UUID, UUID]:
    """A block whose readings fire both trees: low water, low vigour."""
    farm_id, block_id = await _seed_farm_and_block(admin_session, schema, suffix=suffix)
    await _write_index(
        admin_session, schema, block_id=block_id, index_code="ndmi", mean=Decimal("0.10")
    )
    await _write_index(
        admin_session, schema, block_id=block_id, index_code="ndvi", mean=Decimal("0.20")
    )
    return farm_id, block_id


async def _rows(
    session: AsyncSession, schema: str, sql: str, **params: Any
) -> list[dict[str, Any]]:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    stmt = text(sql)
    for name, value in params.items():
        if isinstance(value, UUID):
            stmt = stmt.bindparams(bindparam(name, type_=PG_UUID(as_uuid=True)))
    return [dict(r) for r in (await session.execute(stmt, params)).mappings().all()]


@pytest.mark.asyncio
async def test_only_the_selected_engine_writes(
    admin_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:6]
    tenant = await _tenant_for(admin_session, "eng-one")
    schema = tenant.schema_name
    live_id, _, beta_id, _ = await _two_trees(admin_session, suffix)
    _, block_id = await _dry_block(admin_session, schema, suffix)

    # Other tests leave trees of both stages in the catalogue, so only these
    # two trees' rows are counted.
    mine = "AND tree_id IN (:live, :beta)"
    await _evaluate(schema, tenant.tenant_id, block_id)
    cards = await _rows(
        admin_session,
        schema,
        f"SELECT tree_id FROM recommendations WHERE block_id = :b {mine}",
        b=block_id,
        live=live_id,
        beta=beta_id,
    )
    assert {c["tree_id"] for c in cards} == {live_id}

    await _flip("beta")
    await _evaluate(schema, tenant.tenant_id, block_id)
    open_cards = await _rows(
        admin_session,
        schema,
        f"SELECT tree_id FROM recommendations WHERE block_id = :b AND state = 'open' {mine}",
        b=block_id,
        live=live_id,
        beta=beta_id,
    )
    assert {c["tree_id"] for c in open_cards} == {beta_id}


@pytest.mark.asyncio
async def test_flip_closes_the_outgoing_trees_output(
    admin_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:6]
    tenant = await _tenant_for(admin_session, "eng-close")
    schema = tenant.schema_name
    live_id, live_code, _, _ = await _two_trees(admin_session, suffix)
    _, block_id = await _dry_block(admin_session, schema, suffix)
    await _evaluate(schema, tenant.tenant_id, block_id)

    # One alert from the live tree and one from a rule, which is not a tree
    # and must stay open.
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    for rule_code in (f"tree:{live_code}:leaf_scout", "rule:water_stress"):
        await admin_session.execute(
            text(
                "INSERT INTO alerts (block_id, rule_code, severity) VALUES (:b, :r, 'warning')"
            ).bindparams(bindparam("b", type_=PG_UUID(as_uuid=True))),
            {"b": block_id, "r": rule_code},
        )
    await admin_session.commit()

    before = await _rows(
        admin_session,
        schema,
        "SELECT id FROM recommendations WHERE tree_id = :t AND state = 'open'",
        t=live_id,
    )
    assert before, "the live tree must have opened a card for this test to mean anything"
    verdicts_before = await _rows(
        admin_session,
        schema,
        "SELECT id FROM decision_tree_block_verdicts WHERE tree_id = :t AND valid_to IS NULL",
        t=live_id,
    )
    assert verdicts_before

    result = await _flip("beta")
    assert result["changed"] is True
    assert result["engine"] == "beta"
    counts = result["last_close_out"]["tenants"][schema]
    assert counts["recommendations_expired"] >= len(before)
    assert counts["history_rows"] == counts["recommendations_expired"]
    # At least this test's tree alert. Seeded live trees may add their own.
    assert counts["alerts_resolved"] >= 1
    assert counts["verdicts_closed"] >= len(verdicts_before)

    still_open = await _rows(
        admin_session,
        schema,
        "SELECT id FROM recommendations WHERE tree_id = :t AND state IN ('open', 'deferred')",
        t=live_id,
    )
    assert still_open == []
    history = await _rows(
        admin_session,
        schema,
        "SELECT details FROM recommendations_history "
        "WHERE recommendation_id = :r AND to_state = 'expired'",
        r=before[0]["id"],
    )
    assert [h["details"]["reason"] for h in history] == [RETIRED_REASON]

    alerts = await _rows(
        admin_session,
        schema,
        "SELECT rule_code, status FROM alerts WHERE block_id = :b "
        "AND rule_code IN ('rule:water_stress', :tree_rule) ORDER BY rule_code",
        b=block_id,
        tree_rule=f"tree:{live_code}:leaf_scout",
    )
    assert alerts == [
        {"rule_code": "rule:water_stress", "status": "open"},
        {"rule_code": f"tree:{live_code}:leaf_scout", "status": "resolved"},
    ]
    current = await _rows(
        admin_session,
        schema,
        "SELECT id FROM decision_tree_block_verdicts WHERE tree_id = :t AND valid_to IS NULL",
        t=live_id,
    )
    assert current == []
    # History keeps the verdicts, it only ends them.
    ended = await _rows(
        admin_session,
        schema,
        "SELECT id FROM decision_tree_block_verdicts WHERE tree_id = :t",
        t=live_id,
    )
    assert len(ended) == len(verdicts_before)


@pytest.mark.asyncio
async def test_a_repeated_flip_changes_nothing() -> None:
    first = await _flip("beta")
    assert first["changed"] is True
    second = await _flip("beta")
    assert second["changed"] is False
    assert second["last_close_out"] == first["last_close_out"]

    factory = AsyncSessionLocal()
    async with factory() as session:
        assert (await read_engine(session))["engine"] == "beta"
