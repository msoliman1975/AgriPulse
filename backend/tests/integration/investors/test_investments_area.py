"""The Investments area: investor app logins, the investor's own reads, the
Overview numbers and the farm map, all through the HTTP API.

The investor login runs the real IAM invite flow against the fake Keycloak
client, so the rows it writes (user, membership, Investor role) are real.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.iam import users_service
from app.modules.iam.router import router as iam_router
from app.modules.investors.app_router import router as investor_app_router
from app.modules.investors.router import router as investors_router
from app.shared.auth.context import TenantRole
from app.shared.keycloak import FakeKeycloakClient
from tests.integration.farms.conftest import make_context
from tests.integration.scouting.conftest import ScoutingFixture, StubAuth

pytestmark = [pytest.mark.integration]

_LON0, _LAT0 = 31.6105, 30.6105


@pytest.fixture(autouse=True)
def fake_keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloakClient:
    fake = FakeKeycloakClient()
    monkeypatch.setattr(users_service, "get_keycloak_client", lambda: fake)
    return fake


def _rect(lon: float, lat: float, d: float = 0.001) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]
        ],
    }


def _client(context: Any) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    for r in (farms_router, iam_router, investors_router, investor_app_router):
        app.include_router(r)
    app.add_middleware(StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _sold_holding(env: ScoutingFixture, lon: float = _LON0) -> tuple[dict, dict]:
    """A holding with a current owner, and that owner."""
    async with _client(env.admin_context) as c:
        h = await c.post(
            f"/api/v1/farms/{env.farm_id}/blocks/{env.block_id}/holdings",
            json={"name": f"Strip {lon}", "boundary": _rect(lon, _LAT0), "tree_count": 40},
        )
        assert h.status_code == 201, h.text
        inv = await c.post(
            "/api/v1/investors",
            json={"full_name": "Nour Hassan", "email": f"{uuid4().hex[:8]}@example.com"},
        )
        assert inv.status_code == 201, inv.text
        own = await c.post(
            f"/api/v1/farms/{env.farm_id}/holdings/{h.json()['id']}/ownerships",
            json={"investor_id": inv.json()["id"], "start_date": date.today().isoformat()},
        )
        assert own.status_code == 201, own.text
    return h.json(), inv.json()


async def _login(env: ScoutingFixture, investor_id: str) -> dict:
    async with _client(env.admin_context) as c:
        resp = await c.post(f"/api/v1/investors/{investor_id}:create-login")
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_login_links_a_user_with_the_investor_role(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    _, investor = await _sold_holding(env)
    body = await _login(env, investor["id"])

    assert body["investor"]["user_id"] is not None
    assert body["investor"]["status"] == "invited"
    assert body["investor"]["invited_at"] is not None

    async with _client(env.admin_context) as c:
        again = await c.post(f"/api/v1/investors/{investor['id']}:create-login")
        team = await c.get("/api/v1/users")
    # One login per investor.
    assert again.status_code == 409, again.text
    # Investors are managed from Investments, never listed on Team.
    assert team.status_code == 200, team.text
    assert investor["email"] not in [u["email"] for u in team.json()]


@pytest.mark.asyncio
async def test_disable_and_enable_login_follow_the_status(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    _, investor = await _sold_holding(env)
    await _login(env, investor["id"])
    async with _client(env.admin_context) as c:
        off = await c.post(f"/api/v1/investors/{investor['id']}:disable-login")
        on = await c.post(f"/api/v1/investors/{investor['id']}:enable-login")
    assert off.status_code == 200, off.text
    assert off.json()["status"] == "suspended"
    assert on.status_code == 200, on.text
    # Never used the app yet, so back to "invited", not "active".
    assert on.json()["status"] == "invited"


@pytest.mark.asyncio
async def test_investor_reads_only_their_own_holdings(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    mine, investor = await _sold_holding(env, _LON0)
    theirs, _ = await _sold_holding(env, _LON0 + 0.001)
    body = await _login(env, investor["id"])
    me = make_context(
        user_id=UUID(body["investor"]["user_id"]),
        tenant_id=env.tenant_id,
        tenant_role=TenantRole.INVESTOR,
    )
    async with _client(me) as c:
        who = await c.get("/api/v1/investor/me")
        listed = await c.get("/api/v1/investor/holdings")
        one = await c.get(f"/api/v1/investor/holdings/{mine['id']}")
        other = await c.get(f"/api/v1/investor/holdings/{theirs['id']}")
        staff_route = await c.get(f"/api/v1/farms/{env.farm_id}/holdings")

    assert who.status_code == 200, who.text
    assert who.json()["code"] == investor["code"]
    assert listed.status_code == 200, listed.text
    assert [h["code"] for h in listed.json()] == [mine["code"]]
    assert one.status_code == 200, one.text
    assert one.json()["tree_count"] == 40
    assert one.json()["period"] == "current"
    # Another investor's holding answers like a missing one.
    assert other.status_code == 404, other.text
    # Staff routes stay closed to an investor token.
    assert staff_route.status_code == 403, staff_route.text

    # Using the app moves the investor from invited to active.
    async with _client(env.admin_context) as c:
        after = (await c.get(f"/api/v1/investors/{investor['id']}")).json()
    assert after["status"] == "active"
    assert after["last_app_seen_at"] is not None


@pytest.mark.asyncio
async def test_investor_responses_carry_no_staff_fields(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    mine, investor = await _sold_holding(env)
    body = await _login(env, investor["id"])
    me = make_context(
        user_id=UUID(body["investor"]["user_id"]),
        tenant_id=env.tenant_id,
        tenant_role=TenantRole.INVESTOR,
    )
    async with _client(me) as c:
        one = (await c.get(f"/api/v1/investor/holdings/{mine['id']}")).json()
        who = (await c.get("/api/v1/investor/me")).json()
    for leaked in ("share_pct", "notes_internal", "contract_ref", "block_area_m2", "status"):
        assert leaked not in one, leaked
    for leaked in ("email", "notes_internal", "national_id_last4", "user_id"):
        assert leaked not in who, leaked


@pytest.mark.asyncio
async def test_a_staff_token_has_no_investor_reads(scouting_env: ScoutingFixture) -> None:
    async with _client(scouting_env.admin_context) as c:
        resp = await c.get("/api/v1/investor/holdings")
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_overview_counts_and_areas_for_one_farm(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    sold, _ = await _sold_holding(env, _LON0)
    async with _client(env.admin_context) as c:
        unsold = await c.post(
            f"/api/v1/farms/{env.farm_id}/blocks/{env.block_id}/holdings",
            json={
                "name": "For sale",
                "boundary": _rect(_LON0 + 0.001, _LAT0),
                "status": "available",
            },
        )
        assert unsold.status_code == 201, unsold.text
        ov = await c.get(f"/api/v1/farms/{env.farm_id}/investments/overview")
    assert ov.status_code == 200, ov.text
    o = ov.json()
    farm = o["farm"]
    assert farm["farm_id"] == env.farm_id
    assert o["investors"] == 1
    assert (farm["holdings"], farm["sold"], farm["for_sale"], farm["draft"]) == (2, 1, 1, 0)
    assert float(farm["area_sold_m2"]) == pytest.approx(float(sold["area_m2"]), abs=0.01)
    assert float(farm["area_not_sold_m2"]) == pytest.approx(
        float(farm["block_area_m2"]) - float(sold["area_m2"]), abs=0.01
    )
    assert o["recent"][0]["holding_code"] == sold["code"]
    assert o["all_farms"]["farms"] == 1
    assert o["all_farms"]["sold"] == 1


async def _second_farm(env: ScoutingFixture) -> tuple[str, str]:
    """Another farm with one block, east of the fixture's farm."""
    from tests.integration.farms.test_blocks_unit_type import _polygon
    from tests.integration.farms.test_farms_crud import _square

    async with _client(env.admin_context) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={
                "code": "SC-FARM-2",
                "name": "Second farm",
                "boundary": _square(31.70, 30.60),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm.status_code == 201, farm.text
        block = await c.post(
            f"/api/v1/farms/{farm.json()['id']}/blocks",
            json={"code": "SB2", "boundary": _polygon(31.701, 30.601)},
        )
        assert block.status_code == 201, block.text
    return farm.json()["id"], block.json()["id"]


@pytest.mark.asyncio
async def test_farm_views_count_holdings_on_other_farms(scouting_env: ScoutingFixture) -> None:
    """Seen from one farm, an investor's holdings elsewhere are a count, not rows."""
    env = scouting_env
    here, investor = await _sold_holding(env)
    farm2, block2 = await _second_farm(env)
    async with _client(env.admin_context) as c:
        there = await c.post(
            f"/api/v1/farms/{farm2}/blocks/{block2}/holdings",
            json={"name": "Over there", "boundary": _rect(31.7015, 30.6015)},
        )
        assert there.status_code == 201, there.text
        owned = await c.post(
            f"/api/v1/farms/{farm2}/holdings/{there.json()['id']}/ownerships",
            json={"investor_id": investor["id"], "start_date": date.today().isoformat()},
        )
        assert owned.status_code == 201, owned.text
        fresh = await c.post(
            "/api/v1/investors",
            json={"full_name": "No holdings yet", "email": f"{uuid4().hex[:8]}@example.com"},
        )
        assert fresh.status_code == 201, fresh.text

        listed = await c.get(f"/api/v1/farms/{env.farm_id}/investors")
        holdings = await c.get(f"/api/v1/farms/{env.farm_id}/holdings")

    assert listed.status_code == 200, listed.text
    rows = {r["code"]: r for r in listed.json()}
    # The investor with land here, and the one with no land anywhere yet.
    assert set(rows) == {investor["code"], fresh.json()["code"]}
    me = rows[investor["code"]]
    assert (me["holdings_in_farm"], me["other_farms"], me["other_farm_holdings"]) == (1, 1, 1)
    assert rows[fresh.json()["code"]]["holdings_in_farm"] == 0

    owner = next(h for h in holdings.json() if h["code"] == here["code"])["current_owner"]
    assert owner["other_farm_holdings"] == 1


@pytest.mark.asyncio
async def test_farm_map_returns_blocks_and_holdings(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    sold, _ = await _sold_holding(env)
    async with _client(env.admin_context) as c:
        resp = await c.get(f"/api/v1/farms/{env.farm_id}/holdings-map")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [b["id"] for b in body["blocks"]] == [env.block_id]
    assert body["blocks"][0]["eligible"] is True
    assert [h["code"] for h in body["holdings"]] == [sold["code"]]


async def _rekey(admin_session: Any, *, old_id: UUID, sub: UUID) -> None:
    """What `/me` does on the first sign-in: `public.users.id := sub`."""
    from sqlalchemy import text

    await admin_session.execute(
        text("UPDATE public.users SET id = :new, keycloak_subject = :sub WHERE id = :old"),
        {"new": sub, "sub": str(sub), "old": old_id},
    )
    await admin_session.commit()


async def _users_row(admin_session: Any, email: str) -> tuple[UUID, str]:
    from sqlalchemy import text

    row = (
        await admin_session.execute(
            text("SELECT id, keycloak_subject FROM public.users WHERE email = :e"), {"e": email}
        )
    ).one()
    return row[0], row[1]


def _investor_context(env: ScoutingFixture, sub: UUID, email: str) -> Any:
    """A real token's shape: user_id and keycloak_subject are both the sub."""
    import dataclasses

    base = make_context(user_id=sub, tenant_id=env.tenant_id, tenant_role=TenantRole.INVESTOR)
    return dataclasses.replace(base, keycloak_subject=str(sub), email=email)


@pytest.mark.asyncio
async def test_login_link_survives_the_first_sign_in_rekey(
    scouting_env: ScoutingFixture, admin_session: Any
) -> None:
    """The bug found in production: /me re-keys public.users.id to the sub,
    and the investor's link must still resolve afterwards."""
    env = scouting_env
    mine, investor = await _sold_holding(env)
    body = await _login(env, investor["id"])
    old_id, subject = await _users_row(admin_session, investor["email"])
    sub = UUID(subject)
    # The link is the Keycloak id, which the re-key does not change.
    assert body["investor"]["user_id"] == str(sub)

    me = _investor_context(env, sub, investor["email"])
    async with _client(me) as c:
        before = await c.get("/api/v1/investor/me")
    assert before.status_code == 200, before.text

    await _rekey(admin_session, old_id=old_id, sub=sub)
    async with _client(me) as c:
        after = await c.get("/api/v1/investor/holdings")
    assert after.status_code == 200, after.text
    assert [h["code"] for h in after.json()] == [mine["code"]]

    # Staff actions find the users row behind the link after the re-key too.
    async with _client(env.admin_context) as c:
        resend = await c.post(f"/api/v1/investors/{investor['id']}:resend-login")
        off = await c.post(f"/api/v1/investors/{investor['id']}:disable-login")
    assert resend.status_code == 200, resend.text
    assert off.status_code == 200, off.text


@pytest.mark.asyncio
async def test_a_link_left_dangling_by_an_old_rekey_is_repaired(
    scouting_env: ScoutingFixture, admin_session: Any
) -> None:
    """Links made before the fix stored the pre-re-key users id. The
    investor is found by email and the link is rewritten to the sub."""
    from sqlalchemy import text

    env = scouting_env
    mine, investor = await _sold_holding(env)
    await _login(env, investor["id"])
    old_id, subject = await _users_row(admin_session, investor["email"])
    sub = UUID(subject)
    await admin_session.execute(
        text(f'UPDATE "{env.schema}".investors SET user_id = :old WHERE id = :id'),
        {"old": old_id, "id": UUID(investor["id"])},
    )
    await admin_session.commit()
    await _rekey(admin_session, old_id=old_id, sub=sub)

    me = _investor_context(env, sub, investor["email"])
    async with _client(me) as c:
        who = await c.get("/api/v1/investor/me")
        listed = await c.get("/api/v1/investor/holdings")
    assert who.status_code == 200, who.text
    assert [h["code"] for h in listed.json()] == [mine["code"]]

    async with _client(env.admin_context) as c:
        after = (await c.get(f"/api/v1/investors/{investor['id']}")).json()
    assert after["user_id"] == str(sub)
