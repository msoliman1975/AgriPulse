"""W1-B — the picker that dispatch needs and could not previously build.

`:assign` wants an `assignee_user_id`; `GET /farms/{id}/members` returns
membership rows with no user id and no name. The only way to bridge that was
`GET /users`, which is tenant-scoped, so the farm-level supervisor who needs
the picker could not load it. These assert the farm-scoped route answers it.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam import field_enrolment
from app.modules.scouting.assignees import eligible_roles
from app.shared.keycloak import FakeKeycloakClient
from tests.integration.farms.conftest import FarmRole, FarmScope, make_context
from tests.integration.scouting.conftest import ScoutingFixture, build_app

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def fake_keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloakClient:
    fake = FakeKeycloakClient()
    monkeypatch.setattr(field_enrolment, "get_keycloak_client", lambda: fake)
    return fake


def _client(context):  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def test_eligible_roles_come_from_the_registry() -> None:
    """Derived, not listed — a hand-written set drifts the first time a role
    gains or loses the capability."""
    roles = eligible_roles()
    assert "Scout" in roles
    assert "FieldOperator" in roles
    # A viewer can read a farm but must never appear as somewhere to send work.
    assert "Viewer" not in roles


@pytest.mark.asyncio
async def test_assignees_lists_the_scout_with_a_usable_identity(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    phone = "010" + f"{uuid4().int % 10**8:08d}"
    async with _client(env.admin_context) as client:
        enrolled = await client.post(
            "/api/v1/users/field-enrolment",
            json={
                "phone": phone,
                "full_name": "Sabry Nour",
                "farm_id": env.farm_id,
                "role": "Scout",
            },
        )
    assert enrolled.status_code == 201, enrolled.text
    user_id = enrolled.json()["user_id"]

    async with _client(env.agronomist_context) as client:
        resp = await client.get(f"/api/v1/scouting/assignees?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    rows = {r["user_id"]: r for r in resp.json()}

    assert user_id in rows, "the scout we just enrolled must be sendable"
    scout = rows[user_id]
    assert scout["full_name"] == "Sabry Nour"
    assert scout["role"] == "Scout"
    # The synthetic address is never returned: a picker falling back to it
    # renders `+2010…@scouts…` where a name belongs.
    assert scout["email"] is None
    assert scout["identity_kind"] == "phone"
    assert scout["phone"].startswith("+20")
    # The id the assign endpoint actually wants, and the membership the farm
    # members API speaks in — both, so no client has to join them.
    assert UUID(scout["user_id"])
    assert UUID(scout["membership_id"])


@pytest.mark.asyncio
async def test_a_farm_scoped_supervisor_can_load_the_picker(
    scouting_env: ScoutingFixture,
) -> None:
    """The whole point: this works without `user.read`, which is tenant-scoped."""
    env = scouting_env
    supervisor = make_context(
        user_id=uuid4(),
        tenant_id=env.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(env.farm_id), role=FarmRole.FARM_MANAGER),),
    )
    async with _client(supervisor) as client:
        resp = await client.get(f"/api/v1/scouting/assignees?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_tenant_admin_sees_every_farm(scouting_env: ScoutingFixture) -> None:
    """Decided 2026-08-10: tenant admins hold the scouting capabilities.

    An admin who can invite the people but cannot see the work they are sent
    on is a hole rather than a safeguard. Farm-scoped capabilities resolve
    against the tenant-role branch first, so one tenant role reaches every
    farm without needing a scope on each.
    """
    env = scouting_env
    async with _client(env.admin_context) as client:
        resp = await client.get(f"/api/v1/scouting/assignees?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_a_scout_cannot_enumerate_the_farm(scouting_env: ScoutingFixture) -> None:
    """Reading the roster is dispatching, not doing the visit."""
    env = scouting_env
    async with _client(env.scout_context) as client:
        resp = await client.get(f"/api/v1/scouting/assignees?farm_id={env.farm_id}")
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_revoked_scope_drops_out_of_the_picker(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """Someone taken off the farm must stop being somewhere work can be sent —
    otherwise dispatch silently addresses a person who cannot open it."""
    env = scouting_env
    phone = "010" + f"{uuid4().int % 10**8:08d}"
    async with _client(env.admin_context) as client:
        enrolled = await client.post(
            "/api/v1/users/field-enrolment",
            json={
                "phone": phone,
                "full_name": "Leaving Layla",
                "farm_id": env.farm_id,
                "role": "Scout",
            },
        )
    assert enrolled.status_code == 201, enrolled.text
    membership_id = enrolled.json()["membership_id"]

    await admin_session.execute(
        text(
            "UPDATE public.farm_scopes SET revoked_at = now() "
            "WHERE membership_id = CAST(:m AS uuid)"
        ),
        {"m": membership_id},
    )
    await admin_session.commit()

    async with _client(env.agronomist_context) as client:
        resp = await client.get(f"/api/v1/scouting/assignees?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    assert enrolled.json()["user_id"] not in {r["user_id"] for r in resp.json()}


@pytest.mark.asyncio
async def test_unknown_farm_returns_nothing_rather_than_probing_scopes(
    scouting_env: ScoutingFixture,
) -> None:
    """The farm is checked against the tenant schema first, so a caller cannot
    read `public.farm_scopes` for a farm that is not theirs."""
    env = scouting_env
    stranger = str(uuid4())
    admin_on_other_farm = make_context(
        user_id=uuid4(),
        tenant_id=env.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(stranger), role=FarmRole.FARM_MANAGER),),
    )
    async with _client(admin_on_other_farm) as client:
        resp = await client.get(f"/api/v1/scouting/assignees?farm_id={stranger}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
