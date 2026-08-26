"""Integration tests for `TenantUsersService`.

Covers the full lifecycle of tenant user management:

  * Invite — fresh user, KC succeeds → DB rows + KC user + provisioning="succeeded"
  * Invite — KC down → DB rows still land, kc_subject="pending::<email>", provisioning="pending"
  * Invite — an email live in another tenant is refused; nothing is written
  * Invite — an offboarded person is revived and re-provisioned in the new tenant
  * Invite — existing global user whose KC subject is itself pending → stays pending
  * Invite — duplicate in same tenant raises TenantUserAlreadyExistsError
  * List — surfaces all active memberships + roles + preferences
  * Update — patches user row and upserts user_preferences (lazy-create)
  * Suspend / Reactivate — flips membership.status + KC enable/disable
  * Delete — soft-deletes membership + global user + KC user, and empties the
    farm_scopes claim so a live token stops granting the farms just revoked
  * Cross-tenant safety — admin cannot mutate user in a different tenant

Each test creates its own tenant(s) via the tenancy service so DB state
is isolated. The KC client is the in-memory `FakeKeycloakClient`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.users_service import (
    AlreadyInAnotherTenantError,
    FarmsNotInTenantError,
    LastTenantOwnerError,
    TenantUserAlreadyExistsError,
    TenantUserNotFoundError,
    TenantUsersService,
)
from app.modules.tenancy.service import get_tenant_service
from app.shared.keycloak import FakeKeycloakClient
from app.shared.rbac import FARM_TIER_ROLES, TENANT_TIER_ROLES, RoleNotAssignableError

pytestmark = [pytest.mark.integration]


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


async def _make_tenant(
    admin_session: AsyncSession,
    fake: FakeKeycloakClient,
    *,
    prefix: str,
) -> tuple[str, str]:
    """Create a tenant via the tenancy service. Returns (tenant_id, schema_name)."""
    service = get_tenant_service(admin_session, keycloak_client=fake)
    slug = _slug(prefix)
    result = await service.create_tenant(
        slug=slug,
        name=f"Tenant {slug}",
        contact_email=f"ops@{slug}.test",
        actor_user_id=None,
    )
    return result.tenant_id, result.schema_name


def _users_service(admin_session: AsyncSession, fake: FakeKeycloakClient) -> TenantUsersService:
    return TenantUsersService(public_session=admin_session, keycloak=fake)


async def _tenant_scoped_service(
    admin_session: AsyncSession,
    fake: FakeKeycloakClient,
    *,
    schema: str,
) -> TenantUsersService:
    """A service that can also read `schema`, the way the router builds one.

    Farm-tier grants validate their farm ids against the tenant's `farms`
    table, which a public-only session cannot see. One session serves both
    roles here: every public query in the service is schema-qualified, and
    the farm lookup is the only unqualified one, so it resolves through the
    search_path set below — the same thing `get_db_session` does in
    production from the JWT's tenant claim.

    Setting it here, rather than relying on whatever `_make_farm` left
    behind, is the point: a stale search_path pointed the cross-tenant test
    at the wrong schema and it found the farm it was supposed to reject.
    """
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    return TenantUsersService(
        public_session=admin_session, tenant_session=admin_session, keycloak=fake
    )


async def _make_farm(admin_session: AsyncSession, schema: str, *, code: str) -> UUID:
    """One live farm in `schema`, seeded with SQL.

    The farms API is not mounted in this package, and a role assignment only
    needs the row to exist.
    """
    farm_id = uuid4()
    await admin_session.execute(text(f'SET search_path TO "{schema}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary) "
            "VALUES (:id, :code, :name, ST_GeomFromText("
            "'POLYGON((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0))', 4326))"
        ),
        {"id": str(farm_id), "code": code, "name": f"{code} farm"},
    )
    return farm_id


# =====================================================================
# Invite
# =====================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("role", TENANT_TIER_ROLES)
async def test_invite_accepts_every_tenant_tier_role(
    admin_session: AsyncSession, role: str
) -> None:
    """Every tenant-tier role the invite API offers must be insertable.

    Regression for the default-role 500: the tenant_role_assignments CHECK
    constraint has to accept whatever the invite path writes. The role lands
    via a real DB insert here, which FakeKeycloakClient cannot shortcut, so a
    CHECK that disagrees with the offered list fails this test.

    `Viewer` used to be in this list. It is farm-tier now — it is a FarmRole,
    and a tenant-wide Viewer granted nothing at all, because the JWT claim is
    parsed against the tenant-role enum and the value was dropped.
    """
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="role")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email=f"{role.lower()}@role.test",
        full_name=f"{role} User",
        phone=None,
        tenant_role=role,
        tenant_schema=schema,
        actor_user_id=None,
    )
    assert result["keycloak_provisioning"] == "succeeded"
    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["tenant_roles"] == [role]
    assert rows[0]["farm_roles"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", FARM_TIER_ROLES)
async def test_invite_farm_tier_role_without_farms_is_refused(
    admin_session: AsyncSession, role: str
) -> None:
    """A farm-tier role with no farms would write no role row at all.

    The API layer rejects the pair, but the service is also called directly,
    and silently creating a member with no role is the worst of the outcomes:
    they sign in and every screen 403s with nothing to point at.
    """
    fake = FakeKeycloakClient()
    _tenant_id, schema = await _make_tenant(admin_session, fake, prefix="nofarm")
    svc = _users_service(admin_session, fake)

    with pytest.raises(ValueError, match="granted per farm"):
        await svc.invite_user(
            email=f"{role.lower()}@nofarm.test",
            full_name=f"{role} User",
            phone=None,
            tenant_role=role,
            tenant_schema=schema,
            actor_user_id=None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["PlatformAdmin", "PlatformSupport"])
async def test_invite_refuses_platform_roles(admin_session: AsyncSession, role: str) -> None:
    """A platform role must never be assignable from inside a tenant.

    Refused before any row is written, rather than left to the
    tenant_role_assignments CHECK — which would surface as a 500 rather than
    a validation error, and would not cover the farm_scopes path at all.
    """
    fake = FakeKeycloakClient()
    _tenant_id, schema = await _make_tenant(admin_session, fake, prefix="plat")
    svc = _users_service(admin_session, fake)

    with pytest.raises(RoleNotAssignableError):
        await svc.invite_user(
            email=f"{role.lower()}@plat.test",
            full_name=f"{role} User",
            phone=None,
            tenant_role=role,
            tenant_schema=schema,
            actor_user_id=None,
        )


@pytest.mark.asyncio
async def test_invite_farm_tier_role_writes_farm_scopes(admin_session: AsyncSession) -> None:
    """A farm-tier invite grants through farm_scopes and no tenant role.

    That combination — a member with farm scopes and no tenant assignment —
    is the shape a scout has had since PR #269/#270, and it is what lets a
    farm role stay confined to its farms.
    """
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="fscope")
    farm_id = await _make_farm(admin_session, schema, code="AGR")
    svc = await _tenant_scoped_service(admin_session, fake, schema=schema)

    result = await svc.invite_user(
        email="agronomist@fscope.test",
        full_name="Agronomist User",
        phone=None,
        tenant_role="Agronomist",
        farm_ids=(farm_id,),
        tenant_schema=schema,
        actor_user_id=None,
    )
    assert result["keycloak_provisioning"] == "succeeded"

    rows = await svc.list_users(tenant_id=tenant_id)
    row = next(r for r in rows if r["email"] == "agronomist@fscope.test")
    assert row["tenant_roles"] == []
    assert row["farm_roles"] == [{"farm_id": str(farm_id), "role": "Agronomist"}]

    # The JWT carries farm_scopes, so the Keycloak attribute has to be
    # written too — without it the member signs in and is 403 everywhere.
    kc_user = fake.users[result["keycloak_subject"]]
    assert kc_user.farm_scopes == ({"farm_id": str(farm_id), "role": "Agronomist"},)
    # A farm role is not a realm role, and must not be set as tenant_role.
    assert kc_user.tenant_role is None
    # tenant_id still has to reach the JWT, or there is no tenant context.
    assert kc_user.tenant_id == str(tenant_id)


@pytest.mark.asyncio
async def test_invite_rejects_a_farm_from_another_tenant(admin_session: AsyncSession) -> None:
    """`public.farm_scopes.farm_id` is a logical reference, not a FK.

    Nothing in the database would reject another tenant's farm id, so the
    check has to happen in the service or the grant is accepted and then
    resolves against a farm the member cannot see.
    """
    fake = FakeKeycloakClient()
    _a_id, a_schema = await _make_tenant(admin_session, fake, prefix="xa")
    _b_id, b_schema = await _make_tenant(admin_session, fake, prefix="xb")
    b_farm = await _make_farm(admin_session, b_schema, code="BF")
    svc = await _tenant_scoped_service(admin_session, fake, schema=a_schema)

    with pytest.raises(FarmsNotInTenantError):
        await svc.invite_user(
            email="stranger@xa.test",
            full_name="Stranger",
            phone=None,
            tenant_role="Agronomist",
            farm_ids=(b_farm,),
            tenant_schema=a_schema,
            actor_user_id=None,
        )


# =====================================================================
# Role change
# =====================================================================


@pytest.mark.asyncio
async def test_assign_role_replaces_the_previous_tenant_role(
    admin_session: AsyncSession,
) -> None:
    """Setting a role revokes the old one. Roles do not stack."""
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="chg")
    svc = _users_service(admin_session, fake)
    # An owner has to exist first, or demoting the only member trips the
    # last-owner guard rather than exercising the replacement.
    await svc.invite_user(
        email="owner@chg.test",
        full_name="Owner",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema,
        actor_user_id=None,
    )
    invited = await svc.invite_user(
        email="billing@chg.test",
        full_name="Billing",
        phone=None,
        tenant_role="BillingAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    result = await svc.assign_role(
        user_id=invited["user_id"],
        tenant_id=tenant_id,
        tenant_schema=schema,
        role="TenantAdmin",
        farm_ids=(),
        actor_user_id=None,
    )
    assert result["role"] == "TenantAdmin"
    assert result["revoked"]["tenant_roles"] == ["BillingAdmin"]

    rows = await svc.list_users(tenant_id=tenant_id)
    row = next(r for r in rows if r["email"] == "billing@chg.test")
    assert row["tenant_roles"] == ["TenantAdmin"]

    # The Keycloak attribute drives the JWT claim, so a change that only
    # touched the database would keep granting the revoked role.
    assert fake.users[invited["keycloak_subject"]].tenant_role == "TenantAdmin"


@pytest.mark.asyncio
async def test_assign_role_can_cross_tiers_in_both_directions(
    admin_session: AsyncSession,
) -> None:
    """Tenant -> farm drops the tenant assignment; farm -> tenant drops scopes."""
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="tier")
    farm_id = await _make_farm(admin_session, schema, code="TF")
    svc = await _tenant_scoped_service(admin_session, fake, schema=schema)
    await svc.invite_user(
        email="owner@tier.test",
        full_name="Owner",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema,
        actor_user_id=None,
    )
    invited = await svc.invite_user(
        email="mover@tier.test",
        full_name="Mover",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    # Down to the farm tier.
    await svc.assign_role(
        user_id=invited["user_id"],
        tenant_id=tenant_id,
        tenant_schema=schema,
        role="Scout",
        farm_ids=(farm_id,),
        actor_user_id=None,
    )
    rows = await svc.list_users(tenant_id=tenant_id)
    row = next(r for r in rows if r["email"] == "mover@tier.test")
    assert row["tenant_roles"] == []
    assert row["farm_roles"] == [{"farm_id": str(farm_id), "role": "Scout"}]
    kc_user = fake.users[invited["keycloak_subject"]]
    # Cleared, not left behind: a stale attribute keeps granting TenantAdmin.
    assert kc_user.tenant_role is None
    assert kc_user.farm_scopes == ({"farm_id": str(farm_id), "role": "Scout"},)

    # And back up to the tenant tier.
    await svc.assign_role(
        user_id=invited["user_id"],
        tenant_id=tenant_id,
        tenant_schema=schema,
        role="TenantAdmin",
        farm_ids=(),
        actor_user_id=None,
    )
    rows = await svc.list_users(tenant_id=tenant_id)
    row = next(r for r in rows if r["email"] == "mover@tier.test")
    assert row["tenant_roles"] == ["TenantAdmin"]
    assert row["farm_roles"] == []
    kc_user = fake.users[invited["keycloak_subject"]]
    assert kc_user.tenant_role == "TenantAdmin"
    assert kc_user.farm_scopes == ()


@pytest.mark.asyncio
async def test_assign_role_refuses_to_remove_the_last_owner(
    admin_session: AsyncSession,
) -> None:
    """TenantOwner holds the only capability that can appoint another one.

    A tenant with no owner cannot recover without a PlatformAdmin, so the
    change is refused rather than audited after the fact.
    """
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="last")
    svc = _users_service(admin_session, fake)
    owner = await svc.invite_user(
        email="only@last.test",
        full_name="Only Owner",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema,
        actor_user_id=None,
    )

    with pytest.raises(LastTenantOwnerError):
        await svc.assign_role(
            user_id=owner["user_id"],
            tenant_id=tenant_id,
            tenant_schema=schema,
            role="TenantAdmin",
            farm_ids=(),
            actor_user_id=None,
        )
    # Nothing was revoked on the way to the refusal.
    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["tenant_roles"] == ["TenantOwner"]


@pytest.mark.asyncio
async def test_assign_role_refuses_a_platform_role(admin_session: AsyncSession) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="pesc")
    svc = _users_service(admin_session, fake)
    invited = await svc.invite_user(
        email="climber@pesc.test",
        full_name="Climber",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    with pytest.raises(RoleNotAssignableError):
        await svc.assign_role(
            user_id=invited["user_id"],
            tenant_id=tenant_id,
            tenant_schema=schema,
            role="PlatformAdmin",
            farm_ids=(),
            actor_user_id=None,
        )


@pytest.mark.asyncio
async def test_invite_fresh_user_provisions_keycloak_and_db(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="invok")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="alice@invok.test",
        full_name="Alice Invok",
        phone="+201000000001",
        tenant_role="TenantOwner",
        tenant_schema=schema,
        actor_user_id=None,
    )

    assert result["keycloak_provisioning"] == "succeeded"
    assert result["keycloak_subject"] is not None
    assert not result["keycloak_subject"].startswith("pending::")

    # KC state — exactly one user in the tenant's group with the right role.
    kc_user = fake.users[result["keycloak_subject"]]
    assert kc_user.email == "alice@invok.test"
    assert "TenantOwner" in kc_user.realm_roles

    # DB state — public.users + tenant_memberships + tenant_role_assignments.
    rows = await svc.list_users(tenant_id=tenant_id)
    assert len(rows) == 1
    assert rows[0]["email"] == "alice@invok.test"
    assert rows[0]["tenant_roles"] == ["TenantOwner"]
    assert rows[0]["membership_status"] == "active"
    assert rows[0]["keycloak_subject"] == result["keycloak_subject"]


@pytest.mark.asyncio
async def test_invite_falls_back_to_pending_when_keycloak_fails(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="invpend")
    svc = _users_service(admin_session, fake)

    fake.fail_on = "ensure_group"
    result = await svc.invite_user(
        email="bob@invpend.test",
        full_name="Bob Pending",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    # KC failed — DB still landed with the placeholder subject.
    assert result["keycloak_provisioning"] == "pending"
    assert result["keycloak_subject"] is None

    rows = await svc.list_users(tenant_id=tenant_id)
    assert len(rows) == 1
    assert rows[0]["keycloak_subject"] == "pending::bob@invpend.test"
    assert rows[0]["membership_status"] == "active"
    assert rows[0]["tenant_roles"] == ["TenantAdmin"]
    # KC has no user since ensure_group failed before the create.
    assert all(u.email != "bob@invpend.test" for u in fake.users.values())


@pytest.mark.asyncio
async def test_invite_existing_pending_user_stays_pending(
    admin_session: AsyncSession,
) -> None:
    """A first invite that never reached Keycloak leaves `pending::<email>`.

    Re-inviting that person elsewhere has nothing to attach to, so it stays
    pending and the operator runbook fixes both rows at once.

    The move goes through an offboarding, because a person belongs to one
    tenant: the membership in A is archived before B invites them. That is
    the only route between tenants, so it is the one this pins.
    """
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="pa")
    tenant_b, schema_b = await _make_tenant(admin_session, fake, prefix="pb")
    svc = _users_service(admin_session, fake)

    fake.fail_on = "ensure_group"
    a_result = await svc.invite_user(
        email="ghost@pend.test",
        full_name="Ghost",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_a,
        actor_user_id=None,
    )
    assert a_result["keycloak_provisioning"] == "pending"

    await svc.delete_user(
        user_id=a_result["user_id"],
        tenant_id=tenant_a,
        actor_user_id=None,
        tenant_schema=schema_a,
    )

    # `fail_on` is one-shot, so it has to be re-armed: the point of this test
    # is a second invite with Keycloak *still* down, not a second invite that
    # happens to find it back up.
    fake.fail_on = "ensure_group"
    b_result = await svc.invite_user(
        email="ghost@pend.test",
        full_name="Ghost",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_b,
        actor_user_id=None,
    )
    assert b_result["keycloak_provisioning"] == "pending"
    # The response reports None for a provision that did not happen; the row
    # is what carries the `pending::` marker the operator runbook looks for.
    assert b_result["keycloak_subject"] is None
    b_rows = await svc.list_users(tenant_id=tenant_b)
    assert b_rows[0]["keycloak_subject"] == "pending::ghost@pend.test"


@pytest.mark.asyncio
async def test_invite_duplicate_in_same_tenant_raises(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    _, schema = await _make_tenant(admin_session, fake, prefix="dup")
    svc = _users_service(admin_session, fake)

    await svc.invite_user(
        email="dup@dup.test",
        full_name="Dup",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    with pytest.raises(TenantUserAlreadyExistsError):
        await svc.invite_user(
            email="dup@dup.test",
            full_name="Dup Again",
            phone=None,
            tenant_role="TenantAdmin",
            tenant_schema=schema,
            actor_user_id=None,
        )


# =====================================================================
# Update / preferences
# =====================================================================


@pytest.mark.asyncio
async def test_update_user_patches_profile_and_upserts_prefs(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="upd")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="upd@upd.test",
        full_name="Original Name",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    user_id = result["user_id"]

    await svc.update_user(
        user_id=user_id,
        tenant_id=tenant_id,
        updates={"full_name": "Renamed", "phone": "+201112223334"},
        preferences_patch={"language": "ar", "unit_system": "hectare"},
        actor_user_id=None,
        tenant_schema=schema,
    )

    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["full_name"] == "Renamed"
    assert rows[0]["phone"] == "+201112223334"
    prefs = rows[0]["preferences"]
    assert prefs is not None
    assert prefs.language == "ar"
    assert prefs.unit_system == "hectare"


# =====================================================================
# Suspend / Reactivate
# =====================================================================


@pytest.mark.asyncio
async def test_suspend_then_reactivate_flips_db_and_keycloak(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="susp")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="susp@susp.test",
        full_name="Susp",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    kc_subject = result["keycloak_subject"]
    assert fake.users[kc_subject].enabled is True

    await svc.suspend_user(
        user_id=result["user_id"],
        tenant_id=tenant_id,
        actor_user_id=None,
        tenant_schema=schema,
    )
    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["membership_status"] == "suspended"
    assert fake.users[kc_subject].enabled is False

    await svc.reactivate_user(
        user_id=result["user_id"],
        tenant_id=tenant_id,
        actor_user_id=None,
        tenant_schema=schema,
    )
    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["membership_status"] == "active"
    assert fake.users[kc_subject].enabled is True


@pytest.mark.asyncio
async def test_suspend_succeeds_when_keycloak_throws(
    admin_session: AsyncSession,
) -> None:
    """DB is the source of truth — KC outage doesn't block local suspend."""
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="suspkc")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="suspkc@suspkc.test",
        full_name="SuspKC",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    fake.fail_on = "disable_user"
    # No exception — KC failure is logged-and-continued.
    await svc.suspend_user(
        user_id=result["user_id"],
        tenant_id=tenant_id,
        actor_user_id=None,
        tenant_schema=schema,
    )
    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["membership_status"] == "suspended"


# =====================================================================
# Delete
# =====================================================================


@pytest.mark.asyncio
async def test_delete_user_in_single_tenant_archives_global_and_kc(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="del1")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="del1@del1.test",
        full_name="Del1",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    kc_subject = result["keycloak_subject"]
    assert kc_subject in fake.users

    await svc.delete_user(
        user_id=result["user_id"],
        tenant_id=tenant_id,
        actor_user_id=None,
        tenant_schema=schema,
    )

    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows == []

    # Global user soft-deleted (not visible via list since list joins
    # users.deleted_at IS NULL); confirm directly.
    user_status = (
        await admin_session.execute(
            text("SELECT status, deleted_at FROM public.users WHERE id = :uid").bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True))
            ),
            {"uid": result["user_id"]},
        )
    ).first()
    assert user_status.status == "archived"
    assert user_status.deleted_at is not None

    # KC user removed.
    assert kc_subject not in fake.users

    # No lingering active tenant-role grants for the archived membership
    # (the soft membership-delete doesn't cascade, so delete_user revokes).
    active_roles = (
        await admin_session.execute(
            text(
                "SELECT count(*) AS c FROM public.tenant_role_assignments "
                "WHERE membership_id = :mid AND revoked_at IS NULL"
            ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
            {"mid": result["membership_id"]},
        )
    ).first()
    assert active_roles.c == 0


@pytest.mark.asyncio
async def test_delete_last_tenant_keeps_user_when_platform_admin(
    admin_session: AsyncSession,
) -> None:
    """A platform admin who is also a tenant user, deleted from their last
    tenant, keeps their global user + KC account (they're still a real
    platform account) — only the membership + its grants go. Guards the
    dangling-platform-grant orphan."""
    fake = FakeKeycloakClient()
    tenant_id, schema = await _make_tenant(admin_session, fake, prefix="delplat")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="delplat@delplat.test",
        full_name="Del Platform",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    user_id = result["user_id"]
    kc_subject = result["keycloak_subject"]
    # Grant them an active platform role directly.
    await admin_session.execute(
        text(
            "INSERT INTO public.platform_role_assignments (user_id, role) "
            "VALUES (:uid, 'PlatformAdmin')"
        ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
        {"uid": user_id},
    )

    await svc.delete_user(
        user_id=user_id, tenant_id=tenant_id, actor_user_id=None, tenant_schema=schema
    )

    # Membership gone from the tenant view, grants revoked...
    assert await svc.list_users(tenant_id=tenant_id) == []
    active_roles = (
        await admin_session.execute(
            text(
                "SELECT count(*) AS c FROM public.tenant_role_assignments "
                "WHERE membership_id = :mid AND revoked_at IS NULL"
            ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
            {"mid": result["membership_id"]},
        )
    ).first()
    assert active_roles.c == 0
    # ...but the global user + KC account SURVIVE (still a platform admin).
    user_status = (
        await admin_session.execute(
            text("SELECT status, deleted_at FROM public.users WHERE id = :uid").bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True))
            ),
            {"uid": user_id},
        )
    ).first()
    assert user_status.status == "active"
    assert user_status.deleted_at is None
    assert kc_subject in fake.users


# =====================================================================
# Cross-tenant safety
# =====================================================================


@pytest.mark.asyncio
async def test_admin_in_one_tenant_cannot_modify_user_in_another(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="iso-a")
    tenant_b, schema_b = await _make_tenant(admin_session, fake, prefix="iso-b")
    svc = _users_service(admin_session, fake)

    # User belongs only to tenant A.
    a_result = await svc.invite_user(
        email="iso@iso.test",
        full_name="Iso",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_a,
        actor_user_id=None,
    )

    # Pretend an admin in tenant B tries to suspend / delete / update them.
    with pytest.raises(TenantUserNotFoundError):
        await svc.suspend_user(
            user_id=a_result["user_id"],
            tenant_id=tenant_b,
            actor_user_id=None,
            tenant_schema=schema_b,
        )
    with pytest.raises(TenantUserNotFoundError):
        await svc.update_user(
            user_id=a_result["user_id"],
            tenant_id=tenant_b,
            updates={"full_name": "Hijacked"},
            preferences_patch=None,
            actor_user_id=None,
            tenant_schema=schema_b,
        )
    with pytest.raises(TenantUserNotFoundError):
        await svc.delete_user(
            user_id=a_result["user_id"],
            tenant_id=tenant_b,
            actor_user_id=None,
            tenant_schema=schema_b,
        )

    # Original tenant A row is untouched.
    a_rows = await svc.list_users(tenant_id=tenant_a)
    assert a_rows[0]["full_name"] == "Iso"
    assert a_rows[0]["membership_status"] == "active"


# =====================================================================
# One person, one tenant
# =====================================================================


@pytest.mark.asyncio
async def test_invite_refuses_an_email_live_in_another_tenant(
    admin_session: AsyncSession,
) -> None:
    """A person belongs to one tenant, and nothing is written when refused.

    This replaces a test that asserted the opposite. Attaching the same person
    to a second tenant looked like a feature and could not work: `tenant_id`
    is a single-valued Keycloak attribute so the token names one tenant, while
    `farm_scopes` is multi-valued and spans both. The person got a token that
    named farms it could not reach, and every request against them resolved
    the wrong schema and found nothing.

    The refusal comes before Keycloak is touched. Provisioning first would
    write `tenant_id` on the attach path and point them at the tenant that
    just refused them.
    """
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="one-a")
    tenant_b, schema_b = await _make_tenant(admin_session, fake, prefix="one-b")
    svc = _users_service(admin_session, fake)

    a_result = await svc.invite_user(
        email="one@one.test",
        full_name="One Tenant",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema_a,
        actor_user_id=None,
    )
    kc_subject = a_result["keycloak_subject"]
    groups_before = [g for g in fake.groups.values() if kc_subject in g.member_ids]

    with pytest.raises(AlreadyInAnotherTenantError) as caught:
        await svc.invite_user(
            email="one@one.test",
            full_name="One Tenant",
            phone=None,
            tenant_role="TenantAdmin",
            tenant_schema=schema_b,
            actor_user_id=None,
        )
    assert caught.value.email == "one@one.test"

    # Tenant B gained nobody, tenant A is untouched.
    assert await svc.list_users(tenant_id=tenant_b) == []
    assert len(await svc.list_users(tenant_id=tenant_a)) == 1

    # And Keycloak was not touched: no second group, no second realm role.
    groups_after = [g for g in fake.groups.values() if kc_subject in g.member_ids]
    assert len(groups_after) == len(groups_before) == 1
    assert "TenantAdmin" not in set(fake.users[kc_subject].realm_roles)


@pytest.mark.asyncio
async def test_invite_revives_a_person_offboarded_from_their_last_tenant(
    admin_session: AsyncSession,
) -> None:
    """Offboard, then invite elsewhere — the only way to move between tenants.

    Because that is now the only route, it has to work end to end, and it did
    not. `delete_user` soft-deletes `public.users` and deletes the Keycloak
    account once no membership survives; the invite path then reused the
    archived row as it stood. The person got a membership, a `deleted_at`
    that makes `get_me` raise, and a `keycloak_subject` pointing at an
    account that no longer exists — a member who cannot sign in, with nothing
    reporting it.

    The local id survives on purpose. Audit rows and every logical reference
    to `public.users.id` point at it, so a new row would orphan them.
    """
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="rev-a")
    tenant_b, schema_b = await _make_tenant(admin_session, fake, prefix="rev-b")
    svc = _users_service(admin_session, fake)

    a_result = await svc.invite_user(
        email="rev@rev.test",
        full_name="Revived Rania",
        phone="+201000000001",
        tenant_role="TenantOwner",
        tenant_schema=schema_a,
        actor_user_id=None,
    )
    old_subject = a_result["keycloak_subject"]
    user_id = a_result["user_id"]

    await svc.delete_user(
        user_id=user_id,
        tenant_id=tenant_a,
        actor_user_id=None,
        tenant_schema=schema_a,
    )
    archived = (
        await admin_session.execute(
            text("SELECT status, deleted_at FROM public.users WHERE id = :uid").bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True))
            ),
            {"uid": user_id},
        )
    ).first()
    assert archived.deleted_at is not None, "precondition: offboarding archives the person"

    b_result = await svc.invite_user(
        email="rev@rev.test",
        full_name="Revived Rania",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_b,
        actor_user_id=None,
    )

    assert b_result["user_id"] == user_id, "the same person, not a second row"
    assert b_result["keycloak_provisioning"] == "succeeded"
    assert b_result["keycloak_subject"] != old_subject, "the old account was deleted"

    row = (
        await admin_session.execute(
            text(
                "SELECT status, deleted_at, phone, keycloak_subject "
                "FROM public.users WHERE id = :uid"
            ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
            {"uid": user_id},
        )
    ).first()
    assert row.deleted_at is None
    assert row.status == "active"
    assert row.keycloak_subject == b_result["keycloak_subject"]
    # `phone=None` on the invite means "not stated", not "clear it".
    assert row.phone == "+201000000001"

    assert len(await svc.list_users(tenant_id=tenant_b)) == 1
    assert await svc.list_users(tenant_id=tenant_a) == []


@pytest.mark.asyncio
async def test_delete_empties_the_farm_scopes_claim(
    admin_session: AsyncSession,
) -> None:
    """Offboarding has to reach Keycloak, or the token keeps granting.

    Authorization is read from the token: `_build_context` takes `tenant_id`
    and `farm_scopes` off the claims and never queries Postgres. Revoking the
    rows changes nothing on its own, and a field session carries
    `offline_access` for months.

    The person holds a platform role, which is what keeps their account alive
    through the offboarding — otherwise `delete_user` deletes the Keycloak
    user outright and there is no claim left to inspect. That is also the only
    shape where this can go wrong, now that a person belongs to one tenant:
    an account that survives its last membership.
    """
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="proj")
    svc = _users_service(admin_session, fake)

    result = await svc.invite_user(
        email="proj@proj.test",
        full_name="Projected",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema_a,
        actor_user_id=None,
    )
    kc_subject = result["keycloak_subject"]
    await admin_session.execute(
        text(
            "INSERT INTO public.platform_role_assignments (user_id, role) "
            "VALUES (:uid, 'PlatformSupport')"
        ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
        {"uid": result["user_id"]},
    )

    farm_one, farm_two = uuid4(), uuid4()
    for farm_id in (farm_one, farm_two):
        await admin_session.execute(
            text(
                "INSERT INTO public.farm_scopes (membership_id, farm_id, role) "
                "VALUES (:m, :f, 'FarmManager')"
            ).bindparams(
                bindparam("m", type_=PG_UUID(as_uuid=True)),
                bindparam("f", type_=PG_UUID(as_uuid=True)),
            ),
            {"m": result["membership_id"], "f": farm_id},
        )
    await admin_session.commit()

    await svc.delete_user(
        user_id=result["user_id"],
        tenant_id=tenant_a,
        actor_user_id=None,
        tenant_schema=schema_a,
    )

    assert kc_subject in fake.users, "the platform role keeps the account alive"
    projected = {s["farm_id"] for s in fake.users[kc_subject].farm_scopes}
    assert projected == set(), "every revoked farm must leave the token"
    assert kc_subject in fake.logged_out
