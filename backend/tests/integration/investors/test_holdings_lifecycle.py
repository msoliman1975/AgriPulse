"""Investors, holdings, and ownership, driven through the HTTP API.

The rules under test live partly in the database (tenant migration 0098:
R1 inside the block, R2 no overlap, R6 block redraw, R9 ownership dates) and
partly in the service (R3 shape, R7 inactivation, R8 redraw of a sold
holding, transfers). Each test names the rule it holds.

The block from the scouting fixture is the square 31.61..31.613 E,
30.61..30.613 N.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.investors.router import router as investors_router
from tests.integration.scouting.conftest import ScoutingFixture, StubAuth

pytestmark = [pytest.mark.integration]

# Inside the block, west half of the south strip.
_LON0, _LAT0 = 31.6105, 30.6105


def _rect(lon: float, lat: float, dlon: float = 0.001, dlat: float = 0.001) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [[lon, lat], [lon + dlon, lat], [lon + dlon, lat + dlat], [lon, lat + dlat], [lon, lat]]
        ],
    }


def _client(context: Any) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(investors_router)
    app.add_middleware(StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _investor(env: ScoutingFixture, name: str = "Nour Hassan") -> dict[str, Any]:
    async with _client(env.admin_context) as c:
        resp = await c.post(
            "/api/v1/investors",
            json={"full_name": name, "email": f"{uuid4().hex[:8]}@example.com"},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _holding(
    env: ScoutingFixture, boundary: dict[str, Any], name: str = "North strip"
) -> Any:
    async with _client(env.admin_context) as c:
        return await c.post(
            f"/api/v1/farms/{env.farm_id}/blocks/{env.block_id}/holdings",
            json={"name": name, "boundary": boundary, "tree_count": 120},
        )


@pytest.mark.asyncio
async def test_holding_measures_its_area_and_share(scouting_env: ScoutingFixture) -> None:
    resp = await _holding(scouting_env, _rect(_LON0, _LAT0))
    assert resp.status_code == 201, resp.text
    h = resp.json()

    assert h["code"].startswith("H-")
    assert h["status"] == "draft"
    assert h["tree_count"] == 120
    # 0.001 deg x 0.001 deg at 30.6 N is about 96 m x 111 m.
    assert 9_000 < float(h["area_m2"]) < 12_000
    share = float(h["share_pct"])
    assert share == pytest.approx(float(h["area_m2"]) * 100 / float(h["block_area_m2"]), abs=0.01)
    assert 5 < share < 15
    assert h["current_owner"] is None


@pytest.mark.asyncio
async def test_r1_holding_outside_the_block_is_refused(scouting_env: ScoutingFixture) -> None:
    # Starts inside, runs 0.002 deg past the east edge.
    resp = await _holding(scouting_env, _rect(31.612, _LAT0, dlon=0.003))
    assert resp.status_code == 422, resp.text
    assert resp.json()["type"].endswith("holding-outside-block")


@pytest.mark.asyncio
async def test_r2_overlap_is_refused_but_a_shared_edge_is_not(
    scouting_env: ScoutingFixture,
) -> None:
    first = await _holding(scouting_env, _rect(_LON0, _LAT0), name="A")
    assert first.status_code == 201, first.text

    overlapping = await _holding(scouting_env, _rect(_LON0 + 0.0005, _LAT0), name="B")
    assert overlapping.status_code == 409, overlapping.text
    assert overlapping.json()["type"].endswith("holding-overlap")

    neighbour = await _holding(scouting_env, _rect(_LON0 + 0.001, _LAT0), name="C")
    assert neighbour.status_code == 201, neighbour.text


@pytest.mark.asyncio
async def test_r3_a_holding_with_a_hole_is_refused(scouting_env: ScoutingFixture) -> None:
    outer = _rect(_LON0, _LAT0)["coordinates"][0]
    hole = _rect(_LON0 + 0.0003, _LAT0 + 0.0003, 0.0002, 0.0002)["coordinates"][0]
    resp = await _holding(scouting_env, {"type": "Polygon", "coordinates": [outer, hole]})
    assert resp.status_code == 422, resp.text
    assert resp.json()["type"].endswith("holding-geometry-invalid")


@pytest.mark.asyncio
async def test_owner_then_transfer_keeps_dated_history(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    holding = (await _holding(env, _rect(_LON0, _LAT0))).json()
    first = await _investor(env, "First Owner")
    second = await _investor(env, "Second Owner")
    start = date.today() - timedelta(days=400)
    transfer = date.today() - timedelta(days=30)
    base = f"/api/v1/farms/{env.farm_id}/holdings/{holding['id']}"

    async with _client(env.admin_context) as c:
        r1 = await c.post(
            f"{base}/ownerships",
            json={"investor_id": first["id"], "start_date": start.isoformat()},
        )
        assert r1.status_code == 201, r1.text
        assert r1.json()["status"] == "sold"
        assert r1.json()["current_owner"]["investor_id"] == first["id"]

        # A new owner cannot start on or before the current owner's start.
        bad = await c.post(
            f"{base}/ownerships",
            json={"investor_id": second["id"], "start_date": start.isoformat()},
        )
        assert bad.status_code == 409, bad.text

        r2 = await c.post(
            f"{base}/ownerships",
            json={
                "investor_id": second["id"],
                "start_date": transfer.isoformat(),
                "previous_ended_by": "resale",
            },
        )
        assert r2.status_code == 201, r2.text
        detail = r2.json()

        first_detail = (await c.get(f"/api/v1/investors/{first['id']}")).json()

    assert detail["current_owner"]["investor_id"] == second["id"]
    periods = {o["investor_id"]: o for o in detail["ownerships"]}
    assert periods[first["id"]]["end_date"] == (transfer - timedelta(days=1)).isoformat()
    assert periods[first["id"]]["ended_by"] == "resale"
    assert periods[first["id"]]["period"] == "past"
    assert periods[second["id"]]["period"] == "current"
    # The past owner still sees the record; it no longer counts as current.
    assert first_detail["current_holdings_count"] == 0
    assert len(first_detail["ownerships"]) == 1


@pytest.mark.asyncio
async def test_owned_holding_and_its_investor_cannot_be_archived(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    holding = (await _holding(env, _rect(_LON0, _LAT0))).json()
    investor = await _investor(env)
    async with _client(env.admin_context) as c:
        await c.post(
            f"/api/v1/farms/{env.farm_id}/holdings/{holding['id']}/ownerships",
            json={"investor_id": investor["id"], "start_date": date.today().isoformat()},
        )
        h = await c.post(f"/api/v1/farms/{env.farm_id}/holdings/{holding['id']}:archive")
        i = await c.post(f"/api/v1/investors/{investor['id']}:archive")
    assert h.status_code == 409, h.text
    assert i.status_code == 409, i.text


@pytest.mark.asyncio
async def test_r6_block_redraw_that_cuts_a_holding_is_refused(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    holding = await _holding(env, _rect(_LON0, _LAT0))
    assert holding.status_code == 201, holding.text
    # Shrink the block to its east half; the holding sits in the west half.
    smaller = _rect(31.6115, 30.61, dlon=0.0015, dlat=0.003)
    async with _client(env.admin_context) as c:
        resp = await c.patch(f"/api/v1/blocks/{env.block_id}", json={"boundary": smaller})
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["type"].endswith("block-has-holdings")
    assert holding.json()["code"] in body["holding_codes"]


@pytest.mark.asyncio
async def test_r7_block_with_an_owned_holding_cannot_be_inactivated(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    holding = (await _holding(env, _rect(_LON0, _LAT0))).json()
    investor = await _investor(env)
    async with _client(env.admin_context) as c:
        await c.post(
            f"/api/v1/farms/{env.farm_id}/holdings/{holding['id']}/ownerships",
            json={"investor_id": investor["id"], "start_date": date.today().isoformat()},
        )
        resp = await c.post(f"/api/v1/blocks/{env.block_id}/inactivate", json={})
    assert resp.status_code == 409, resp.text
    assert resp.json()["type"].endswith("block-has-holdings")


@pytest.mark.asyncio
async def test_an_investment_manager_runs_holdings_end_to_end(
    scouting_env: ScoutingFixture,
) -> None:
    """The new staff role: draws, sells, and redraws a sold holding."""
    from app.shared.auth.context import TenantRole
    from tests.integration.farms.conftest import make_context

    env = scouting_env
    manager = make_context(
        user_id=uuid4(), tenant_id=env.tenant_id, tenant_role=TenantRole.INVESTMENT_MANAGER
    )
    async with _client(manager) as c:
        created = await c.post(
            f"/api/v1/farms/{env.farm_id}/blocks/{env.block_id}/holdings",
            json={"name": "Manager strip", "boundary": _rect(_LON0, _LAT0)},
        )
        assert created.status_code == 201, created.text
        inv = await c.post(
            "/api/v1/investors",
            json={"full_name": "Owner", "email": f"{uuid4().hex[:8]}@example.com"},
        )
        assert inv.status_code == 201, inv.text
        url = f"/api/v1/farms/{env.farm_id}/holdings/{created.json()['id']}"
        sold = await c.post(
            f"{url}/ownerships",
            json={"investor_id": inv.json()["id"], "start_date": date.today().isoformat()},
        )
        assert sold.status_code == 201, sold.text
        redrawn = await c.patch(url, json={"boundary": _rect(_LON0, _LAT0, 0.0008, 0.0008)})
    assert redrawn.status_code == 200, redrawn.text
    assert float(redrawn.json()["area_m2"]) < float(created.json()["area_m2"])


@pytest.mark.asyncio
async def test_farm_roles_have_no_holding_rights(scouting_env: ScoutingFixture) -> None:
    """Investments is separate from farm work: an agronomist sees none of it."""
    env = scouting_env
    created = await _holding(env, _rect(_LON0, _LAT0))
    assert created.status_code == 201, created.text
    async with _client(env.agronomist_context) as c:
        listed = await c.get(f"/api/v1/farms/{env.farm_id}/holdings")
        drawn = await c.post(
            f"/api/v1/farms/{env.farm_id}/blocks/{env.block_id}/holdings",
            json={"name": "Nope", "boundary": _rect(_LON0 + 0.001, _LAT0)},
        )
        investors = await c.get("/api/v1/investors")
        overview = await c.get(f"/api/v1/farms/{env.farm_id}/investments/overview")
    assert listed.status_code == 403, listed.text
    assert drawn.status_code == 403, drawn.text
    assert investors.status_code == 403, investors.text
    assert overview.status_code == 403, overview.text


@pytest.mark.asyncio
async def test_block_context_reports_sold_and_unsold_area(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    a = (await _holding(env, _rect(_LON0, _LAT0), name="A")).json()
    await _holding(env, _rect(_LON0 + 0.001, _LAT0), name="B")
    investor = await _investor(env)
    async with _client(env.admin_context) as c:
        await c.post(
            f"/api/v1/farms/{env.farm_id}/holdings/{a['id']}/ownerships",
            json={"investor_id": investor["id"], "start_date": date.today().isoformat()},
        )
        ctx = (await c.get(f"/api/v1/farms/{env.farm_id}/blocks/{env.block_id}/holdings")).json()
    assert ctx["eligible"] is True
    assert len(ctx["holdings"]) == 2
    assert float(ctx["sold_area_m2"]) == pytest.approx(float(a["area_m2"]), abs=0.01)
    assert float(ctx["unsold_area_m2"]) == pytest.approx(
        float(ctx["block_area_m2"]) - float(a["area_m2"]), abs=0.01
    )


@pytest.mark.asyncio
async def test_duplicate_investor_email_is_refused(scouting_env: ScoutingFixture) -> None:
    async with _client(scouting_env.admin_context) as c:
        one = await c.post(
            "/api/v1/investors", json={"full_name": "One", "email": "same@example.com"}
        )
        two = await c.post(
            "/api/v1/investors", json={"full_name": "Two", "email": "SAME@example.com"}
        )
    assert one.status_code == 201, one.text
    assert one.json()["code"] == "INV-0001"
    assert two.status_code == 409, two.text
