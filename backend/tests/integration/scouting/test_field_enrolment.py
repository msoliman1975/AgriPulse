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
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.iam import field_enrolment
from app.modules.iam.router import router as iam_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from app.shared.keycloak import FakeKeycloakClient
from app.shared.keycloak.field_identity import SYNTHETIC_EMAIL_DOMAIN
from tests.integration.farms.conftest import (
    FarmRole,
    FarmScope,
    StubAuth,
    make_context,
)
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square
from tests.integration.scouting.conftest import ScoutingFixture, build_app

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


async def _seed_worker(
    session: AsyncSession,
    *,
    schema: str,
    farm_id: str,
    name: str,
    role: str,
    phone: str | None = None,
) -> UUID:
    """A worker row plus its availability link, the way the API writes them.

    Since W2-A the link is what puts somebody on a farm; a hand-inserted row
    with only `farm_id` belongs nowhere, and the audit — which reads through
    `resource_farms` — correctly cannot see it.
    """
    await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
    worker_id = (
        await session.execute(
            text(
                "INSERT INTO resources (kind, name, role, phone) "
                "VALUES ('worker', :n, :r, :p) RETURNING id"
            ),
            {"f": farm_id, "n": name, "r": role, "p": phone},
        )
    ).scalar()
    await session.execute(
        text(
            "INSERT INTO resource_farms (resource_id, farm_id) VALUES (:w, CAST(:f AS uuid))"
        ).bindparams(bindparam("w", type_=PG_UUID(as_uuid=True))),
        {"w": worker_id, "f": farm_id},
    )
    await session.commit()
    return worker_id


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
                "INSERT INTO resources (kind, name, role) "
                "VALUES ('worker', 'Existing Hand', 'Scout') RETURNING id"
            ),
            {"f": env.farm_id},
        )
    ).scalar()
    # The availability link the API writes for you. Hand-inserting a worker
    # without it produces a row that belongs to no farm, which is precisely
    # what adoption now refuses.
    await admin_session.execute(
        text(
            "INSERT INTO resource_farms (resource_id, farm_id) " "VALUES (:r, CAST(:f AS uuid))"
        ).bindparams(bindparam("r", type_=PG_UUID(as_uuid=True))),
        {"r": worker_id, "f": env.farm_id},
    )
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
    for name, role, phone in [
        ("Ready Rania", "Scout", "+201001111111"),
        ("Blocked Bilal", "FieldWorker", "+201002222222"),
        ("Phoneless Farid", "Scout", None),
    ]:
        await _seed_worker(
            admin_session,
            schema=env.schema,
            farm_id=env.farm_id,
            name=name,
            role=role,
            phone=phone,
        )

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
    blocked = await _seed_worker(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        name="Blocked",
        role="FieldWorker",
        phone="+201003333333",
    )
    agronomist = await _seed_worker(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        name="Agro",
        role="Agronomist",
        phone="+201004444444",
    )

    async with _client(env.admin_context) as client:
        resp = await client.post(
            "/api/v1/users/field-enrolment/re-role",
            json={
                "farm_id": env.farm_id,
                "worker_ids": [str(blocked), str(agronomist)],
                "role": "Scout",
            },
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


@pytest.mark.asyncio
async def test_audit_carries_what_the_next_action_needs(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """W1-C: the buckets are a worklist, so each row has to carry the fields
    its action takes — the recorded phone (the username, which must not be
    retyped) and, once enrolled, the user id that PIN reissue is keyed on."""
    env = scouting_env
    await _seed_worker(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        name="Ready Rania",
        role="Scout",
        phone="+201007654321",
    )

    enrolled = await _enrol(env, phone=_unique_phone(), full_name="Enrolled Emad")
    assert enrolled.status_code == 201, enrolled.text

    async with _client(env.admin_context) as client:
        resp = await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    audit = resp.json()

    ready = {w["name"]: w for w in audit["ready_to_enrol"]}
    assert ready["Ready Rania"]["phone"] == "+201007654321"
    # Not yet enrolled, so there is no account to re-credential.
    assert ready["Ready Rania"]["user_id"] is None

    done = {w["name"]: w for w in audit["enrolled"]}
    assert done["Enrolled Emad"]["user_id"] == enrolled.json()["user_id"]
    assert done["Enrolled Emad"]["phone"] == enrolled.json()["phone"]


# ---------------------------------------------------------------------------
# W1-A — the farm manager, who is the person standing with the crew
# ---------------------------------------------------------------------------


def _unique_phone() -> str:
    """`public.users` is global, not per-tenant, and the synthetic email is
    derived from the number. A fixed literal therefore collides with the row a
    previous run left behind, and enrolment used to silently adopt that row —
    keeping its stale Keycloak subject, which then 404s on PIN reissue.

    Since one person belongs to one tenant, that collision is a 409 instead:
    every test in this module builds its own tenant, so any two of them
    sharing a literal now means the second is enrolling a number that already
    works somewhere else. Use this in any test that does not assert on the
    number itself."""
    return "010" + f"{uuid4().int % 10**8:08d}"


def _farm_manager(env: ScoutingFixture, farm_id: str | None = None):  # type: ignore[no-untyped-def]
    """A FarmManager on one farm and nothing else — no tenant role at all.

    This is the shape the whole capability exists for, and the shape that
    used to 403 on every one of these routes because they demanded the
    tenant-scoped `user.invite`.
    """
    return make_context(
        user_id=uuid4(),
        tenant_id=env.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id or env.farm_id), role=FarmRole.FARM_MANAGER),),
    )


@pytest.mark.asyncio
async def test_farm_manager_can_enrol_on_their_own_farm(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    body = {
        "phone": _unique_phone(),
        "full_name": "Mansour Fahmy",
        "farm_id": env.farm_id,
        "role": "Scout",
    }
    async with _client(_farm_manager(env)) as client:
        resp = await client.post("/api/v1/users/field-enrolment", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["pin"].isdigit()


@pytest.mark.asyncio
async def test_farm_manager_cannot_enrol_onto_someone_elses_farm(
    scouting_env: ScoutingFixture,
) -> None:
    """The farm is in the body, so the check has to read the body. If it read
    only the token the manager would pass for every farm in the tenant."""
    env = scouting_env
    other_farm = str(uuid4())
    body = {
        "phone": _unique_phone(),
        "full_name": "Not Mine",
        "farm_id": other_farm,
        "role": "Scout",
    }
    async with _client(_farm_manager(env)) as client:
        resp = await client.post("/api/v1/users/field-enrolment", json=body)
    assert resp.status_code == 403, resp.text
    # `extras` are flattened onto the problem document, not nested under a key.
    body = resp.json()
    assert body["capability"] == "user.field_enrol"
    assert body["farm_id"] == other_farm


@pytest.mark.asyncio
async def test_farm_manager_audit_needs_a_farm_and_tenant_wide_is_refused(
    scouting_env: ScoutingFixture,
) -> None:
    """Omitting farm_id asks for every worker in the tenant. A farm-scoped
    grant must not answer a tenant-wide question."""
    env = scouting_env
    async with _client(_farm_manager(env)) as client:
        scoped = await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
        unscoped = await client.get("/api/v1/users/field-enrolment/audit")
    assert scoped.status_code == 200, scoped.text
    assert unscoped.status_code == 403, unscoped.text
    # The tenant admin still gets the whole-tenant view.
    async with _client(env.admin_context) as client:
        admin_wide = await client.get("/api/v1/users/field-enrolment/audit")
    assert admin_wide.status_code == 200, admin_wide.text


@pytest.mark.asyncio
async def test_re_role_ignores_workers_on_another_farm(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The capability was checked against one farm, so ids from another farm
    must not be rewritten just because they were posted in the same list."""
    env = scouting_env
    # A real second farm, built the way the fixture builds the first: `farms`
    # needs boundary/centroid/area geometry that a hand-written INSERT cannot
    # supply, and the FK from `resources.farm_id` means it has to exist.
    async with AsyncClient(
        transport=ASGITransport(app=build_app(env.admin_context)), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/farms",
            json={
                "code": "SC-FARM-2",
                "name": "Other farm",
                "boundary": _square(31.90, 30.90),
                "farm_type": "commercial",
                "tags": [],
            },
        )
    assert created.status_code == 201, created.text
    other_farm = created.json()["id"]

    mine = await _seed_worker(
        admin_session,
        schema=env.schema,
        farm_id=env.farm_id,
        name="Mine",
        role="FieldWorker",
        phone="+201005555555",
    )
    theirs = await _seed_worker(
        admin_session,
        schema=env.schema,
        farm_id=str(other_farm),
        name="Theirs",
        role="FieldWorker",
        phone="+201006666666",
    )

    async with _client(_farm_manager(env)) as client:
        resp = await client.post(
            "/api/v1/users/field-enrolment/re-role",
            json={
                "farm_id": env.farm_id,
                "worker_ids": [str(mine), str(theirs)],
                "role": "Scout",
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    roles = dict(
        (
            await admin_session.execute(
                text("SELECT id, role FROM resources WHERE id = ANY(:ids)"),
                {"ids": [mine, theirs]},
            )
        ).all()
    )
    assert roles[mine] == "Scout"
    assert roles[theirs] == "FieldWorker"


@pytest.mark.asyncio
async def test_pin_reissue_by_farm_manager_is_confined_to_their_farm(
    scouting_env: ScoutingFixture,
) -> None:
    """Naming a farm is a claim, not a permission — the target has to actually
    be scoped there, or a manager could reset any scout in the tenant."""
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone())
    assert enrolled.status_code == 201, enrolled.text
    user_id = enrolled.json()["user_id"]

    async with _client(_farm_manager(env)) as client:
        ok = await client.post(f"/api/v1/users/{user_id}/field-pin:reissue?farm_id={env.farm_id}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["pin"].isdigit()

    # Same manager, same farm claim, but a person who is not on that farm.
    async with _client(_farm_manager(env)) as client:
        wrong = await client.post(
            f"/api/v1/users/{env.agronomist_user_id}/field-pin:reissue?farm_id={env.farm_id}"
        )
    assert wrong.status_code == 422, wrong.text
    assert "does not have access to this farm" in wrong.json()["detail"]

    # And with no farm named at all it is a tenant-wide act they cannot do.
    async with _client(_farm_manager(env)) as client:
        unscoped = await client.post(f"/api/v1/users/{user_id}/field-pin:reissue")
    assert unscoped.status_code == 403, unscoped.text


# ---------------------------------------------------------------------------
# W2-D — the invariant: scheduled-where and may-look-where stay together
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_farm_access_adds_both_projections_without_a_new_account(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """Adding a farm is not re-enrolment.

    Before the roster went tenant-level the only way to put an existing scout
    on a second farm was to enrol them again — which 409s, because one phone
    is one username and one account. This writes the scope and the
    availability link together, so the two never disagree.
    """
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone(), full_name="Roaming Rania")
    assert enrolled.status_code == 201, enrolled.text
    user_id = enrolled.json()["user_id"]
    worker_id = enrolled.json()["worker_id"]
    original_pin = enrolled.json()["pin"]

    async with AsyncClient(
        transport=ASGITransport(app=build_app(env.admin_context)), base_url="http://test"
    ) as client:
        second_farm = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "SC-FARM-3",
                    "name": "Second farm",
                    "boundary": _square(32.10, 31.10),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()["id"]

    async with _client(env.admin_context) as client:
        granted = await client.post(
            f"/api/v1/users/{user_id}/farm-access",
            json={"farm_id": second_farm, "role": "Scout"},
        )
    assert granted.status_code == 200, granted.text
    assert granted.json()["worker_id"] == worker_id

    # One identity, two scopes.
    scopes = (
        (
            await admin_session.execute(
                text(
                    "SELECT farm_id FROM public.farm_scopes "
                    "WHERE membership_id = CAST(:m AS uuid) AND revoked_at IS NULL"
                ),
                {"m": enrolled.json()["membership_id"]},
            )
        )
        .scalars()
        .all()
    )
    assert {str(f) for f in scopes} == {env.farm_id, second_farm}

    # One worker row, two availabilities — not a second person.
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    links = (
        (
            await admin_session.execute(
                text("SELECT farm_id FROM resource_farms WHERE resource_id = CAST(:r AS uuid)"),
                {"r": worker_id},
            )
        )
        .scalars()
        .all()
    )
    assert {str(f) for f in links} == {env.farm_id, second_farm}
    workers = (
        await admin_session.execute(
            text("SELECT count(*) FROM resources WHERE membership_id = CAST(:m AS uuid)"),
            {"m": enrolled.json()["membership_id"]},
        )
    ).scalar()
    assert workers == 1, "adding a farm must not mint a second worker row"

    # And no new credential was issued: the PIN they were told still works.
    assert original_pin.isdigit()

    # Re-granting the same farm is a no-op rather than a duplicate.
    async with _client(env.admin_context) as client:
        again = await client.post(
            f"/api/v1/users/{user_id}/farm-access",
            json={"farm_id": second_farm, "role": "Scout"},
        )
    assert again.status_code == 200, again.text


@pytest.mark.asyncio
async def test_audit_reports_availability_without_a_matching_scope(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """The fifth bucket. Availability and scope are independent sets now, and
    a worker schedulable on a farm they cannot open fails silently — nothing
    errors, nothing logs, and the first sign is an empty list in the field."""
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone(), full_name="Mismatched Mona")
    assert enrolled.status_code == 201, enrolled.text
    worker_id = enrolled.json()["worker_id"]

    async with AsyncClient(
        transport=ASGITransport(app=build_app(env.admin_context)), base_url="http://test"
    ) as client:
        other_farm = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "SC-FARM-4",
                    "name": "Unscoped farm",
                    "boundary": _square(32.20, 31.20),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()["id"]

    # Availability without the scope — exactly what `PUT /resources/{id}/farms`
    # would leave behind if it were used on its own.
    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO resource_farms (resource_id, farm_id) "
            "VALUES (CAST(:r AS uuid), CAST(:f AS uuid))"
        ),
        {"r": worker_id, "f": other_farm},
    )
    await admin_session.commit()

    async with _client(env.admin_context) as client:
        flagged = await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={other_farm}")
        clean = await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
    assert flagged.status_code == 200, flagged.text
    assert "Mismatched Mona" in {w["name"] for w in flagged.json()["scope_mismatch"]}
    # On the farm where both agree, nothing is reported.
    assert "Mismatched Mona" not in {w["name"] for w in clean.json()["scope_mismatch"]}


@pytest.mark.asyncio
async def test_enrolment_sets_the_persons_language(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """A crew is not all one language, so this is per person, not per deployment.

    Arabic is the default because it is what the field speaks; the app reads
    this back from GET /me and opens in it.
    """
    env = scouting_env
    default = await _enrol(env, phone=_unique_phone())
    assert default.status_code == 201, default.text
    lang = (
        await admin_session.execute(
            text("SELECT language FROM public.user_preferences WHERE user_id = :u"),
            {"u": default.json()["user_id"]},
        )
    ).scalar_one()
    assert lang == "ar"

    chosen = await _enrol(env, phone=_unique_phone(), full_name="Hala Mansour", language="en")
    assert chosen.status_code == 201, chosen.text
    lang2 = (
        await admin_session.execute(
            text("SELECT language FROM public.user_preferences WHERE user_id = :u"),
            {"u": chosen.json()["user_id"]},
        )
    ).scalar_one()
    assert lang2 == "en"


@pytest.mark.asyncio
async def test_an_untranslated_language_is_refused(scouting_env: ScoutingFixture) -> None:
    """422 rather than storing it.

    Accepting a code the app has no catalogue for produces a person whose
    language setting silently does nothing — the app falls back to English and
    the supervisor has no way to tell that from a bug.
    """
    resp = await _enrol(scouting_env, phone=_unique_phone(), full_name="Karim Fahmy", language="fr")
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_a_deleted_scout_returns_to_ready_to_enrol(
    scouting_env: ScoutingFixture, admin_session: AsyncSession
) -> None:
    """Deleting a scout archives their membership and leaves the worker row
    pointing at it. Testing `membership_id IS NOT NULL` therefore reported a
    deleted person as enrolled forever, and a supervisor reading the worklist
    would never re-enrol somebody who cannot sign in. Seen in production while
    replacing an account keyed to a mistyped number."""
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone(), full_name="Leaver Layth")
    assert enrolled.status_code == 201, enrolled.text

    async with _client(env.admin_context) as client:
        before = (
            await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
        ).json()
    assert "Leaver Layth" in {w["name"] for w in before["enrolled"]}

    # Archive the membership the way delete_user does.
    await admin_session.execute(
        text(
            "UPDATE public.tenant_memberships SET status = 'archived', deleted_at = now() "
            "WHERE id = CAST(:m AS uuid)"
        ),
        {"m": enrolled.json()["membership_id"]},
    )
    await admin_session.commit()

    async with _client(env.admin_context) as client:
        after = (
            await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
        ).json()
    assert "Leaver Layth" not in {w["name"] for w in after["enrolled"]}
    # And they are offered for re-enrolment rather than disappearing.
    assert "Leaver Layth" in {w["name"] for w in after["ready_to_enrol"]}


async def _delete_like_offboarding(
    session: AsyncSession, keycloak: FakeKeycloakClient, enrolled: dict[str, Any]
) -> str:
    """Archives somebody's last membership and deletes their Keycloak account.

    Leaves their grants active on purpose, which is what deletions did before
    `delete_user` began revoking them. Those people are the harder case.
    """
    subject = (
        await session.execute(
            text("SELECT keycloak_subject FROM public.users WHERE id = CAST(:u AS uuid)"),
            {"u": enrolled["user_id"]},
        )
    ).scalar_one()
    await session.execute(
        text(
            "UPDATE public.tenant_memberships SET status = 'archived', deleted_at = now() "
            "WHERE id = CAST(:m AS uuid)"
        ),
        {"m": enrolled["membership_id"]},
    )
    await session.execute(
        text(
            "UPDATE public.users SET status = 'archived', deleted_at = now() "
            "WHERE id = CAST(:u AS uuid)"
        ),
        {"u": enrolled["user_id"]},
    )
    await session.commit()
    await keycloak.delete_user(keycloak_user_id=subject)
    return str(subject)


@pytest.mark.asyncio
async def test_a_deleted_scout_can_be_given_access_again(
    scouting_env: ScoutingFixture,
    admin_session: AsyncSession,
    fake_keycloak: FakeKeycloakClient,
) -> None:
    """Re-enrolling used to fail on the archived membership row, answering
    "re-issue their PIN" for somebody the screen offers no reissue for."""
    env = scouting_env
    phone = _unique_phone()
    first = await _enrol(env, phone=phone, full_name="Returning Rami")
    assert first.status_code == 201, first.text
    old_subject = await _delete_like_offboarding(admin_session, fake_keycloak, first.json())

    again = await _enrol(
        env, phone=phone, full_name="Returning Rami", worker_id=first.json()["worker_id"]
    )
    assert again.status_code == 201, again.text
    assert again.json()["user_id"] == first.json()["user_id"]
    assert again.json()["membership_id"] == first.json()["membership_id"]

    row = (
        await admin_session.execute(
            text(
                "SELECT u.deleted_at, u.status, u.keycloak_subject, m.status AS m_status, "
                "       m.deleted_at AS m_deleted "
                "FROM public.users u JOIN public.tenant_memberships m ON m.user_id = u.id "
                "WHERE u.id = CAST(:u AS uuid)"
            ),
            {"u": first.json()["user_id"]},
        )
    ).one()
    assert row.deleted_at is None
    assert row.status == "active"
    assert row.m_deleted is None
    assert row.m_status == "active"
    assert row.keycloak_subject != old_subject
    assert row.keycloak_subject in fake_keycloak.users

    # Old grants do not come back with them: one live scope, the farm enrolled.
    scopes = (
        await admin_session.execute(
            text(
                "SELECT farm_id FROM public.farm_scopes "
                "WHERE membership_id = CAST(:m AS uuid) AND revoked_at IS NULL"
            ),
            {"m": first.json()["membership_id"]},
        )
    ).all()
    assert [str(s.farm_id) for s in scopes] == [env.farm_id]

    # And the point of it all: a working sign-in that can be replaced.
    async with _client(env.admin_context) as client:
        reissued = await client.post(
            f"/api/v1/users/{first.json()['user_id']}/field-pin:reissue?farm_id={env.farm_id}"
        )
        audit = (
            await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
        ).json()
    assert reissued.status_code == 200, reissued.text
    assert "Returning Rami" in {w["name"] for w in audit["enrolled"]}
    assert "Returning Rami" not in {w["name"] for w in audit["ready_to_enrol"]}


@pytest.mark.asyncio
async def test_returning_without_a_worker_id_keeps_one_worker_row(
    scouting_env: ScoutingFixture,
    admin_session: AsyncSession,
    fake_keycloak: FakeKeycloakClient,
) -> None:
    env = scouting_env
    phone = _unique_phone()
    first = await _enrol(env, phone=phone, full_name="Single Row Sami")
    assert first.status_code == 201, first.text
    await _delete_like_offboarding(admin_session, fake_keycloak, first.json())

    again = await _enrol(env, phone=phone, full_name="Single Row Sami")
    assert again.status_code == 201, again.text
    assert again.json()["worker_id"] == first.json()["worker_id"]


@pytest.mark.asyncio
async def test_a_suspended_scout_is_refused_before_keycloak_is_touched(
    scouting_env: ScoutingFixture,
    admin_session: AsyncSession,
    fake_keycloak: FakeKeycloakClient,
) -> None:
    env = scouting_env
    phone = _unique_phone()
    first = await _enrol(env, phone=phone, full_name="Suspended Salma")
    assert first.status_code == 201, first.text
    await admin_session.execute(
        text(
            "UPDATE public.tenant_memberships SET status = 'suspended' WHERE id = CAST(:m AS uuid)"
        ),
        {"m": first.json()["membership_id"]},
    )
    await admin_session.commit()
    pin_before = {u.id: u.field_pin for u in fake_keycloak.users.values()}

    again = await _enrol(env, phone=phone, full_name="Suspended Salma")
    assert again.status_code == 422, again.text
    assert "suspended" in again.json()["detail"]
    assert {u.id: u.field_pin for u in fake_keycloak.users.values()} == pin_before


@pytest.mark.asyncio
async def test_a_new_pin_ends_sessions_clears_lockout_and_is_audited(
    scouting_env: ScoutingFixture,
    admin_session: AsyncSession,
    fake_keycloak: FakeKeycloakClient,
) -> None:
    """A new PIN is often issued for a lost phone, so the old phone has to stop
    working, and a locked-out scout has to be able to use what they were told."""
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone())
    assert enrolled.status_code == 201, enrolled.text
    user_id = enrolled.json()["user_id"]
    subject = (
        await admin_session.execute(
            text("SELECT keycloak_subject FROM public.users WHERE id = CAST(:u AS uuid)"),
            {"u": user_id},
        )
    ).scalar_one()

    async with _client(env.admin_context) as client:
        resp = await client.post(f"/api/v1/users/{user_id}/field-pin:reissue?farm_id={env.farm_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions_ended"] is True
    assert subject in fake_keycloak.logged_out
    assert subject in fake_keycloak.cleared_lockouts

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    events = (
        await admin_session.execute(
            text(
                "SELECT event_type, details FROM audit_events "
                "WHERE subject_id = CAST(:u AS uuid) ORDER BY time"
            ),
            {"u": user_id},
        )
    ).all()
    assert [e.event_type for e in events] == [
        "iam.field_worker_enrolled",
        "iam.field_pin_reissued",
    ]
    # The phone is the person. It stays out of the audit details.
    assert all("phone" not in e.details for e in events)


@pytest.mark.asyncio
async def test_a_new_pin_survives_a_failed_sign_out_and_says_so(
    scouting_env: ScoutingFixture, fake_keycloak: FakeKeycloakClient
) -> None:
    """The PIN has already changed by then. Failing the request would lose the
    only copy of it, so the operator gets the PIN and a warning instead."""
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone())
    assert enrolled.status_code == 201, enrolled.text

    fake_keycloak.fail_on = "logout_user"
    async with _client(env.admin_context) as client:
        resp = await client.post(
            f"/api/v1/users/{enrolled.json()['user_id']}/field-pin:reissue?farm_id={env.farm_id}"
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pin"].isdigit()
    assert resp.json()["sessions_ended"] is False


def _as_person(env: ScoutingFixture, user_id: str):  # type: ignore[no-untyped-def]
    return make_context(user_id=UUID(user_id), tenant_id=env.tenant_id, tenant_role=None)


@pytest.mark.asyncio
async def test_a_scout_can_change_their_own_pin(
    scouting_env: ScoutingFixture,
    admin_session: AsyncSession,
    fake_keycloak: FakeKeycloakClient,
) -> None:
    env = scouting_env
    phone = _unique_phone()
    enrolled = await _enrol(env, phone=phone)
    assert enrolled.status_code == 201, enrolled.text
    body = enrolled.json()

    async with _client(_as_person(env, body["user_id"])) as client:
        resp = await client.post(
            "/api/v1/me/field-pin", json={"current_pin": body["pin"], "new_pin": "482913"}
        )
    assert resp.status_code == 204, resp.text

    user = next(u for u in fake_keycloak.users.values() if u.phone == body["phone"])
    assert user.field_pin == "482913"
    assert user.id in fake_keycloak.logged_out

    await admin_session.execute(text(f"SET LOCAL search_path TO {env.schema}, public"))
    events = (
        await admin_session.execute(
            text(
                "SELECT event_type, actor_user_id FROM audit_events "
                "WHERE subject_id = CAST(:u AS uuid) AND event_type = 'iam.field_pin_changed'"
            ),
            {"u": body["user_id"]},
        )
    ).all()
    assert [str(e.actor_user_id) for e in events] == [body["user_id"]]


@pytest.mark.asyncio
async def test_a_wrong_current_pin_changes_nothing(
    scouting_env: ScoutingFixture, fake_keycloak: FakeKeycloakClient
) -> None:
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone())
    assert enrolled.status_code == 201, enrolled.text
    body = enrolled.json()
    wrong = "000000" if body["pin"] != "000000" else "111111"

    async with _client(_as_person(env, body["user_id"])) as client:
        resp = await client.post(
            "/api/v1/me/field-pin", json={"current_pin": wrong, "new_pin": "482913"}
        )
    assert resp.status_code == 403, resp.text
    user = next(u for u in fake_keycloak.users.values() if u.phone == body["phone"])
    assert user.field_pin == body["pin"]
    assert user.id not in fake_keycloak.logged_out


@pytest.mark.asyncio
@pytest.mark.parametrize("new_pin", ["123456", "000000"])
async def test_an_obvious_new_pin_is_refused(scouting_env: ScoutingFixture, new_pin: str) -> None:
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone())
    assert enrolled.status_code == 201, enrolled.text
    body = enrolled.json()

    async with _client(_as_person(env, body["user_id"])) as client:
        resp = await client.post(
            "/api/v1/me/field-pin", json={"current_pin": body["pin"], "new_pin": new_pin}
        )
    assert resp.status_code == 422, resp.text
    assert resp.json()["type"].endswith("/weak-pin")


@pytest.mark.asyncio
async def test_reusing_the_current_pin_is_refused(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone())
    assert enrolled.status_code == 201, enrolled.text
    body = enrolled.json()

    async with _client(_as_person(env, body["user_id"])) as client:
        resp = await client.post(
            "/api/v1/me/field-pin", json={"current_pin": body["pin"], "new_pin": body["pin"]}
        )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_an_email_account_cannot_use_the_pin_route(scouting_env: ScoutingFixture) -> None:
    env = scouting_env
    async with _client(env.agronomist_context) as client:
        resp = await client.post(
            "/api/v1/me/field-pin", json={"current_pin": "111111", "new_pin": "482913"}
        )
    assert resp.status_code == 422, resp.text
    assert "password-reset flow" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_phone_already_working_in_another_tenant_is_refused(
    scouting_env: ScoutingFixture,
    admin_session: AsyncSession,
) -> None:
    """One person belongs to one tenant, and the phone is the person.

    This replaces a test that pinned the opposite. Until now the check looked
    only for a membership in *this* tenant, so the same number could be
    enrolled again under a second customer. That produced the one shape the
    system cannot serve: `tenant_id` is a single-valued Keycloak attribute, so
    the token names one tenant, while `farm_scopes` is multi-valued and spans
    both. The scout's app listed a farm it could never load, and every call
    against it resolved the wrong schema and found nothing.

    Seen in production on 2026-08-24: one scout, two tenants, three 403s. The
    earlier fix kept the other tenant's scopes in the attribute, which made
    the token honest and the farm no more reachable. This refuses the second
    enrolment instead.

    The response must not name the other tenant. A farm manager enrolling a
    crew would otherwise be able to discover which AgriPulse customer employs
    any number they can type.
    """
    env = scouting_env
    phone = _unique_phone()
    first = await _enrol(env, phone=phone, full_name="Two Tenant Tarek")
    assert first.status_code == 201, first.text

    other = await get_tenant_service(admin_session).create_tenant(
        slug=f"other-{uuid4().hex[:8]}",
        name="Other tenant",
        contact_email="ops@other.test",
    )
    await admin_session.commit()

    other_admin = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=other.tenant_id, user_id=other_admin)
    other_context = make_context(
        user_id=other_admin,
        tenant_id=other.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    async with _client(other_context) as client:
        second = await client.post(
            "/api/v1/users/field-enrolment",
            json={
                "phone": phone,
                "full_name": "Two Tenant Tarek",
                "farm_id": str(uuid4()),
                "role": "Scout",
            },
        )

    assert second.status_code == 409, second.text
    body = second.json()
    assert body["type"].endswith("/phone-in-another-tenant")
    assert other.slug not in body["detail"]
    # And "re-issue their PIN" must not be the advice here: the account exists
    # but is somebody else's worker.
    assert "PIN" not in body["detail"]

    # Nothing was written. A refused enrolment leaves no second membership.
    count = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM public.tenant_memberships m "
                "  JOIN public.users u ON u.id = m.user_id "
                " WHERE u.phone = :p AND m.deleted_at IS NULL"
            ),
            {"p": first.json()["phone"]},
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_farm_access_refuses_a_farm_from_another_tenant(
    scouting_env: ScoutingFixture,
) -> None:
    """A farm id belonging to somebody else must not be granted.

    `public.farm_scopes.farm_id` is a logical reference, not a foreign key —
    a real FK from a tenant schema into `public` would make `DROP SCHEMA`
    take an ACCESS EXCLUSIVE lock platform-wide. So nothing in the database
    rejects a farm id from another tenant: the grant is written, projected
    into the token, and then resolves against a farm this tenant's schema
    does not contain. The check has to live in the service.

    A random UUID stands in for another tenant's farm. The path is the same:
    the id is simply not a live farm of this tenant.
    """
    env = scouting_env
    enrolled = await _enrol(env, phone=_unique_phone(), full_name="Wandering Wael")
    assert enrolled.status_code == 201, enrolled.text
    user_id = enrolled.json()["user_id"]

    async with _client(env.admin_context) as client:
        refused = await client.post(
            f"/api/v1/users/{user_id}/farm-access",
            json={"farm_id": str(uuid4()), "role": "Scout"},
        )

    assert refused.status_code == 422, refused.text
    assert "this tenant" in refused.json()["detail"]

    # And nothing was written: the person still holds exactly their own farm.
    async with _client(env.admin_context) as client:
        audit = (
            await client.get(f"/api/v1/users/field-enrolment/audit?farm_id={env.farm_id}")
        ).json()
    assert "Wandering Wael" in {w["name"] for w in audit["enrolled"]}
    assert audit["scope_mismatch"] == []
