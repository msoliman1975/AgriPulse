"""Investor harvest on Postgres (build plan 3.6, decisions D1 and D2).

The investor sees their holding's share of each pick inside their ownership,
with gross revenue and totals, and never the block's own figures.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.harvest.router import router as harvest_router
from app.shared.auth.context import TenantRole
from tests.integration.farms.conftest import make_context
from tests.integration.investors.test_investments_area import (
    _LON0,
    _client,
    _login,
    _sold_holding,
)
from tests.integration.scouting.conftest import ScoutingFixture, StubAuth

pytestmark = [pytest.mark.integration]


def _harvest_client(context: Any) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(harvest_router)
    app.add_middleware(StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _pick(c: AsyncClient, env: ScoutingFixture, **body: Any) -> None:
    r = await c.post(f"/api/v1/blocks/{env.block_id}/harvest-lots", json=body)
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_investor_sees_their_share_of_each_pick(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    mine, investor = await _sold_holding(env, _LON0)  # 40 trees, owned from today
    theirs, _ = await _sold_holding(env, _LON0 + 0.001)
    # The block holds 400 trees: the holding's share is 40 / 400.
    await admin_session.execute(
        text(f"UPDATE {env.schema}.blocks SET plant_count = 400 WHERE id = :b"),
        {"b": env.block_id},
    )
    await admin_session.commit()

    today = date.today()
    this_season = str(today.year)
    async with _harvest_client(env.admin_context) as c:
        await _pick(
            c,
            env,
            harvested_on=today.isoformat(),
            weight_kg="1000",
            price_per_kg="10",
            notes_internal="buyer: secret",
        )
        await _pick(c, env, harvested_on=(today + timedelta(days=1)).isoformat(), weight_kg="500")
        # Before the ownership began: not theirs.
        await _pick(
            c,
            env,
            harvested_on=(today - timedelta(days=1)).isoformat(),
            weight_kg="777",
            price_per_kg="10",
        )
        await _pick(
            c,
            env,
            harvested_on=today.isoformat(),
            weight_kg="80",
            price_per_kg="5",
            season_label="1999",
        )

    body = await _login(env, investor["id"])
    me = make_context(
        user_id=UUID(body["investor"]["user_id"]),
        tenant_id=env.tenant_id,
        tenant_role=TenantRole.INVESTOR,
    )
    async with _client(me) as c:
        r = await c.get(f"/api/v1/investor/holdings/{mine['id']}/harvest")
        older = await c.get(
            f"/api/v1/investor/holdings/{mine['id']}/harvest", params={"season": "1999"}
        )
        other = await c.get(f"/api/v1/investor/holdings/{theirs['id']}/harvest")

    assert r.status_code == 200, r.text
    out = r.json()
    assert out["season"] == this_season
    assert out["seasons"] == [this_season, "1999"]
    assert out["currency"] == "EGP"
    assert [Decimal(p["weight_kg"]) for p in out["picks"]] == [Decimal("100"), Decimal("50")]
    assert Decimal(out["picks"][0]["revenue"]) == Decimal("1000")
    assert out["picks"][1]["revenue"] is None
    assert Decimal(out["total_weight_kg"]) == Decimal("150")
    assert Decimal(out["total_revenue"]) == Decimal("1000")
    assert Decimal(out["average_price_per_kg"]) == Decimal("10")
    # Nothing about the block as a whole, the share, or staff notes.
    flat = r.text
    for leaked in ("notes_internal", "secret", "share", "block", "1500", "777"):
        assert leaked not in flat, leaked

    assert older.status_code == 200, older.text
    assert [Decimal(p["weight_kg"]) for p in older.json()["picks"]] == [Decimal("8")]

    assert other.status_code == 404, other.text


@pytest.mark.asyncio
async def test_without_a_block_tree_count_the_split_is_by_area(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    mine, investor = await _sold_holding(env, _LON0)
    await admin_session.execute(
        text(f"UPDATE {env.schema}.blocks SET plant_count = NULL WHERE id = :b"),
        {"b": env.block_id},
    )
    block_area = (
        await admin_session.execute(
            text(f"SELECT area_m2 FROM {env.schema}.blocks WHERE id = :b"), {"b": env.block_id}
        )
    ).scalar_one()
    await admin_session.commit()
    async with _harvest_client(env.admin_context) as c:
        await _pick(c, env, harvested_on=date.today().isoformat(), weight_kg="1000")

    body = await _login(env, investor["id"])
    me = make_context(
        user_id=UUID(body["investor"]["user_id"]),
        tenant_id=env.tenant_id,
        tenant_role=TenantRole.INVESTOR,
    )
    async with _client(me) as c:
        out = (await c.get(f"/api/v1/investor/holdings/{mine['id']}/harvest")).json()

    expected = (Decimal("1000") * Decimal(mine["area_m2"]) / Decimal(block_area)).quantize(
        Decimal("0.01")
    )
    assert Decimal(out["picks"][0]["weight_kg"]) == expected
