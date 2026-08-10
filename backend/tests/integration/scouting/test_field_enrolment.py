"""Enrolling a field worker who has a phone but no email (S-1).

The point of this endpoint is that a scout is not one row. These assert all
five layers land together, because the failure mode being designed against is
the half-provisioned worker: someone who can sign in but is scoped to nothing,
or scoped to a farm but invisible on the work board.

Keycloak is `FakeKeycloakClient`, injected via the `fake_keycloak` fixture
below, so what is proven is the local half plus the shape of the realm call —
not the realm write itself.

It must be injected explicitly. An earlier version of this file assumed the
container would fall back to the *no-op* client and asserted nothing about it;
that held only on a machine with a Keycloak running. In CI
`keycloak_provisioning_enabled` is false and `get_keycloak_client()` returns a
client that *raises* `KeycloakNotConfiguredError` rather than shrugging, so all
four tests here failed while passing locally.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.iam import field_enrolment
from app.modules.iam.router import router as iam_router
from app.shared.keycloak import FakeKeycloakClient
from app.shared.keycloak.field_identity import SYNTHETIC_EMAIL_DOMAIN
from tests.integration.farms.conftest import StubAuth
from tests.integration.scouting.conftest import ScoutingFixture

pytestmark = [pytest.mark.integration]


@pytest.fixture(autouse=True)
def fake_keycloak(monkeypatch: pytest.MonkeyPatch) -> FakeKeycloakClient:
    """Give every test in this module an in-memory realm.

    Patched at `field_enrolment.get_keycloak_client` because the router builds
    its service inline rather than through a FastAPI dependency, so there is no
    `dependency_overrides` seam. `FieldEnrolmentService` resolves the client as
    `keycloak or get_keycloak_client()`, which makes this the one injection
    point that covers both the enrolment and the PIN-reissue paths.
    """
    fake = FakeKeycloakClient()
    monkeypatch.setattr(field_enrolment, "get_keycloak_client", lambda: fake)
    return fake


def _client(context):  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(iam_router)
    app.add_middleware(StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _enrol(env: ScoutingFixture, **overrides: Any):  # type: ignore[no-untyped-def]
    body = {
        "phone": "01001234567",
        "full_name": "Youssef Barakat",
        "farm_id": env.farm_id,
        "role": "Scout",
        **overrides,
    }
    async with _client(env.admin_context) as client:
        return await client.post("/api/v1/users/field-enrolment", json=body)


@pytest.mark.asyncio
async def test_enrolment_creates_all_five_layers(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    env = scouting_env
    resp = await _enrol(env)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Whatever the supervisor typed, one canonical number comes back.
    assert body["phone"] == "+201001234567"
    assert body["pin"].isdigit()
    assert len(body["pin"]) == 6
    assert body["worker_id"] is not None

    user = (
        await admin_session.execute(
            text("SELECT email, phone, full_name FROM public.users WHERE id = :u"),
            {"u": body["user_id"]},
        )
    ).one()
    # Synthetic address satisfies the NOT NULL/UNIQUE constraint; the phone is
    # stored alongside it so support can find someone by the number they know.
    assert user.email == f"201001234567@{SYNTHETIC_EMAIL_DOMAIN}"
    assert user.phone == "+201001234567"

    membership = (
        await admin_session.execute(
            text("SELECT status FROM public.tenant_memberships WHERE id = :m"),
            {"m": body["membership_id"]},
        )
    ).one()
    assert membership.status == "active"

    # No tenant role at all — a scout is farm-scoped only.
    roles = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.tenant_role_assignments WHERE membership_id = :m"),
            {"m": body["membership_id"]},
        )
    ).scalar()
    assert roles == 0

    scope = (
        await admin_session.execute(
            text(
                "SELECT farm_id, role FROM public.farm_scopes "
                "WHERE membership_id = :m AND revoked_at IS NULL"
            ),
            {"m": body["membership_id"]},
        )
    ).one()
    assert str(scope.farm_id) == env.farm_id
    assert scope.role == "Scout"

    # Push, not email: the address is synthetic and nothing can be delivered to
    # it, so the system default would opt them into a channel going nowhere.
    channels = (
        await admin_session.execute(
            text("SELECT notification_channels FROM public.user_preferences WHERE user_id = :u"),
            {"u": body["user_id"]},
        )
    ).scalar()
    assert "push" in list(channels)
    assert "email" not in list(channels)

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    worker = (
        await admin_session.execute(
            text("SELECT name, role, phone, membership_id FROM resources WHERE id = :w"),
            {"w": body["worker_id"]},
        )
    ).one()
    # Linked through membership_id (U-3) — without this they can sign in but
    # cannot be assigned anything.
    assert str(worker.membership_id) == body["membership_id"]
    assert worker.role == "Scout"
    assert worker.phone == "+201001234567"


@pytest.mark.asyncio
async def test_same_number_twice_is_rejected(scouting_env: ScoutingFixture) -> None:
    """Two spellings of one number must not become two accounts."""
    env = scouting_env
    first = await _enrol(env, phone="01009998877")
    assert first.status_code == 201, first.text

    # Same person, written the way a different supervisor would write it.
    again = await _enrol(env, phone="+20 100 999 8877")
    assert again.status_code == 409, again.text
    assert "already has app access" in again.json()["detail"]


@pytest.mark.asyncio
async def test_unusable_phone_and_role_are_refused(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    bad_phone = await _enrol(env, phone="12")
    assert bad_phone.status_code == 422, bad_phone.text

    # FarmManager is not enrollable from here: granting it off the workers
    # screen would be privilege escalation dressed up as a convenience.
    bad_role = await _enrol(env, phone="01005554443", role="FarmManager")
    assert bad_role.status_code == 422, bad_role.text


@pytest.mark.asyncio
async def test_enrolment_can_adopt_an_existing_worker_row(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """A farm that already tracks this person must not get a second row."""
    env = scouting_env
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    worker_id = (
        await admin_session.execute(
            text(
                "INSERT INTO resources (farm_id, kind, name, role) "
                "VALUES (CAST(:f AS uuid), 'worker', 'Existing Hand', 'Scout') RETURNING id"
            ),
            {"f": env.farm_id},
        )
    ).scalar()
    await admin_session.commit()

    resp = await _enrol(env, phone="01007776655", worker_id=str(worker_id))
    assert resp.status_code == 201, resp.text
    assert resp.json()["worker_id"] == str(worker_id)

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    count = (
        await admin_session.execute(text("SELECT count(*) FROM resources WHERE kind = 'worker'"))
    ).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_audit_separates_who_can_be_enrolled_from_who_cannot(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The audit is the pre-flight for a pilot: two of its buckets are silent
    failures rather than errors."""
    env = scouting_env
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    for name, role, phone in [
        ("Ready Rania", "Scout", "+201001111111"),
        ("Blocked Bilal", "FieldWorker", "+201002222222"),
        ("Phoneless Farid", "Scout", None),
    ]:
        await admin_session.execute(
            text(
                "INSERT INTO resources (farm_id, kind, name, role, phone) "
                "VALUES (CAST(:f AS uuid), 'worker', :n, :r, :p)"
            ),
            {"f": env.farm_id, "n": name, "r": role, "p": phone},
        )
    await admin_session.commit()

    async with _client(env.admin_context) as client:
        resp = await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    audit = resp.json()

    assert audit["total"] == 3
    assert [w["name"] for w in audit["ready_to_enrol"]] == ["Ready Rania"]
    # FieldWorker holds no capabilities — schedulable, but can never sign in.
    assert [w["name"] for w in audit["blocked_by_role"]] == ["Blocked Bilal"]
    # The phone is the username, so no phone means no possible account.
    assert [w["name"] for w in audit["missing_phone"]] == ["Phoneless Farid"]
    assert audit["enrolled"] == []


@pytest.mark.asyncio
async def test_re_role_only_touches_field_workers(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """A bulk action that could rewrite any role would be a way to grant
    Agronomist to a dozen people at once."""
    env = scouting_env
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    blocked = (
        await admin_session.execute(
            text(
                "INSERT INTO resources (farm_id, kind, name, role, phone) "
                "VALUES (CAST(:f AS uuid), 'worker', 'Blocked', 'FieldWorker', '+201003333333') "
                "RETURNING id"
            ),
            {"f": env.farm_id},
        )
    ).scalar()
    agronomist = (
        await admin_session.execute(
            text(
                "INSERT INTO resources (farm_id, kind, name, role, phone) "
                "VALUES (CAST(:f AS uuid), 'worker', 'Agro', 'Agronomist', '+201004444444') "
                "RETURNING id"
            ),
            {"f": env.farm_id},
        )
    ).scalar()
    await admin_session.commit()

    async with _client(env.admin_context) as client:
        resp = await client.post(
            "/api/v1/users/field-enrolment/re-role",
            json={"worker_ids": [str(blocked), str(agronomist)], "role": "Scout"},
        )
    assert resp.status_code == 200, resp.text
    # Only the FieldWorker moved; the Agronomist was passed in and ignored.
    assert resp.json()["updated"] == 1

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    roles = dict(
        (
            await admin_session.execute(
                text("SELECT id, role FROM resources WHERE id = ANY(:ids)"),
                {"ids": [blocked, agronomist]},
            )
        ).all()
    )
    assert roles[blocked] == "Scout"
    assert roles[agronomist] == "Agronomist"


@pytest.mark.asyncio
async def test_pin_reissue_works_for_field_users_and_refuses_real_accounts(
    scouting_env: ScoutingFixture,
) -> None:
    env = scouting_env
    enrolled = await _enrol(env, phone="01008887766")
    assert enrolled.status_code == 201, enrolled.text
    original_pin = enrolled.json()["pin"]
    user_id = enrolled.json()["user_id"]

    async with _client(env.admin_context) as client:
        again = await client.post(f"/api/v1/users/{user_id}/field-pin:reissue")
    assert again.status_code == 200, again.text
    # A PIN cannot be looked up — Keycloak stores only its hash — so recovery
    # is replacement, and the new one must actually be new.
    assert again.json()["pin"].isdigit()
    assert again.json()["pin"] != original_pin

    # A colleague who signs in with a real email must not be resettable from
    # the workers screen.
    async with _client(env.admin_context) as client:
        refused = await client.post(f"/api/v1/users/{env.agronomist_user_id}/field-pin:reissue")
    assert refused.status_code == 422, refused.text
    assert "password-reset flow" in refused.json()["detail"]
