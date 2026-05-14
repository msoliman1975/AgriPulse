"""Integration tests for `TenantUsersService`.

Covers the full lifecycle of tenant user management:

  * Invite — fresh user, KC succeeds → DB rows + KC user + provisioning="succeeded"
  * Invite — KC down → DB rows still land, kc_subject="pending::<email>", provisioning="pending"
  * Invite — existing global user (member of another tenant) attaches to new
    tenant via add_existing_user_to_group; provisioning="succeeded"
  * Invite — existing global user whose KC subject is itself pending → stays pending
  * Invite — duplicate in same tenant raises TenantUserAlreadyExistsError
  * List — surfaces all active memberships + roles + preferences
  * Update — patches user row and upserts user_preferences (lazy-create)
  * Suspend / Reactivate — flips membership.status + KC enable/disable
  * Delete (single-tenant) — soft-deletes membership + global user + KC user
  * Delete (multi-tenant) — soft-deletes membership only; global user + KC stay
  * Cross-tenant safety — admin cannot mutate user in a different tenant

Each test creates its own tenant(s) via the tenancy service so DB state
is isolated. The KC client is the in-memory `FakeKeycloakClient`.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.users_service import (
    TenantUserAlreadyExistsError,
    TenantUserNotFoundError,
    TenantUsersService,
)
from app.modules.tenancy.service import get_tenant_service
from app.shared.keycloak import FakeKeycloakClient

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


# =====================================================================
# Invite
# =====================================================================


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
async def test_invite_existing_global_user_attaches_to_new_tenant(
    admin_session: AsyncSession,
) -> None:
    """The bug this test pins: re-inviting the same email to a second tenant
    used to leave the user pending::<email> with a TODO for the operator.
    Now it calls add_existing_user_to_group so the user can sign in to
    both tenants without manual kcadm.sh."""
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="cross-a")
    tenant_b, schema_b = await _make_tenant(admin_session, fake, prefix="cross-b")
    svc = _users_service(admin_session, fake)

    # Tenant A invite — fresh user, succeeds.
    a_result = await svc.invite_user(
        email="cross@cross.test",
        full_name="Cross Tenant",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema_a,
        actor_user_id=None,
    )
    assert a_result["keycloak_provisioning"] == "succeeded"
    kc_subject = a_result["keycloak_subject"]
    assert kc_subject is not None

    # Tenant B invite — same email. Should reuse global user + attach to B's group.
    b_result = await svc.invite_user(
        email="cross@cross.test",
        full_name="Cross Tenant",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_b,
        actor_user_id=None,
    )
    assert b_result["keycloak_provisioning"] == "succeeded"
    # Same global keycloak subject — not a new user.
    assert b_result["keycloak_subject"] == kc_subject

    # KC state: one user, member of two groups, both roles.
    assert len(fake.users) == 1
    user = fake.users[kc_subject]
    assert {"TenantOwner", "TenantAdmin"} <= set(user.realm_roles)
    member_groups = [g for g in fake.groups.values() if kc_subject in g.member_ids]
    assert len(member_groups) == 2

    # DB: same user_id appears in both tenants' membership lists.
    a_rows = await svc.list_users(tenant_id=tenant_a)
    b_rows = await svc.list_users(tenant_id=tenant_b)
    assert len(a_rows) == 1
    assert len(b_rows) == 1
    assert a_rows[0]["id"] == b_rows[0]["id"]
    assert a_rows[0]["tenant_roles"] == ["TenantOwner"]
    assert b_rows[0]["tenant_roles"] == ["TenantAdmin"]


@pytest.mark.asyncio
async def test_invite_existing_pending_user_stays_pending(
    admin_session: AsyncSession,
) -> None:
    """If the original invite couldn't reach KC (subject = pending::<email>),
    re-inviting to a second tenant has nothing to attach to. Stays pending —
    operator runbook fixes both at once."""
    fake = FakeKeycloakClient()
    _, schema_a = await _make_tenant(admin_session, fake, prefix="pa")
    _, schema_b = await _make_tenant(admin_session, fake, prefix="pb")
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

    # Tenant B invite — same email, KC is back online but the existing
    # global user has a pending:: subject. Still pending.
    b_result = await svc.invite_user(
        email="ghost@pend.test",
        full_name="Ghost",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_b,
        actor_user_id=None,
    )
    assert b_result["keycloak_provisioning"] == "pending"
    assert b_result["keycloak_subject"] == "pending::ghost@pend.test"


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


@pytest.mark.asyncio
async def test_delete_user_in_multi_tenant_keeps_global_and_kc(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_a, schema_a = await _make_tenant(admin_session, fake, prefix="delm-a")
    tenant_b, schema_b = await _make_tenant(admin_session, fake, prefix="delm-b")
    svc = _users_service(admin_session, fake)

    a_result = await svc.invite_user(
        email="delm@delm.test",
        full_name="Delm",
        phone=None,
        tenant_role="TenantOwner",
        tenant_schema=schema_a,
        actor_user_id=None,
    )
    kc_subject = a_result["keycloak_subject"]
    await svc.invite_user(
        email="delm@delm.test",
        full_name="Delm",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema_b,
        actor_user_id=None,
    )

    # Delete from tenant A only.
    await svc.delete_user(
        user_id=a_result["user_id"],
        tenant_id=tenant_a,
        actor_user_id=None,
        tenant_schema=schema_a,
    )

    # A: gone. B: still there.
    assert await svc.list_users(tenant_id=tenant_a) == []
    b_rows = await svc.list_users(tenant_id=tenant_b)
    assert len(b_rows) == 1
    assert b_rows[0]["id"] == a_result["user_id"]

    # Global user row still active.
    user_status = (
        await admin_session.execute(
            text("SELECT status, deleted_at FROM public.users WHERE id = :uid").bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True))
            ),
            {"uid": a_result["user_id"]},
        )
    ).first()
    assert user_status.status == "active"
    assert user_status.deleted_at is None

    # KC user still present (other tenant still relies on them).
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
