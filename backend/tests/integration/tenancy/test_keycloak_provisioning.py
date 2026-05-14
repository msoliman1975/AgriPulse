"""Provisioning + retry path tests using FakeKeycloakClient.

When `create_tenant` is called with `owner_email`, the service should:
  - call `ensure_group(slug)` → group_id stored on the tenant row
  - call `invite_user(email, ..., group_id, roles=("TenantOwner",))`
  - leave status='active'

If Keycloak fails mid-way:
  - status flips to 'pending_provision'
  - pending_owner_email/full_name persist for the retry endpoint

`retry_provisioning` re-runs ensure_group + invite_user and clears the
pending state on success.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import (
    InvalidStatusTransitionError,
    NothingToProvisionError,
    get_tenant_service,
)
from app.shared.keycloak import FakeKeycloakClient

pytestmark = [pytest.mark.integration]


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_create_tenant_provisions_owner_via_keycloak(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)
    slug = _slug("provs")
    actor = uuid4()

    result = await service.create_tenant(
        slug=slug,
        name="Provisioned",
        contact_email="ops@provs.test",
        owner_email="owner@provs.test",
        owner_full_name="Owner Name",
        actor_user_id=actor,
    )

    assert result.status == "active"
    assert result.provisioning_failed is False
    assert result.owner_user_id is not None

    snapshot = await service.get_tenant(result.tenant_id)
    assert snapshot.keycloak_group_id is not None
    assert snapshot.pending_owner_email is None

    # FakeKeycloakClient state confirms what was sent.
    assert len(fake.groups) == 1
    group = next(iter(fake.groups.values()))
    assert group.slug == slug
    assert len(group.member_ids) == 1
    user = fake.users[group.member_ids[0]]
    assert user.email == "owner@provs.test"
    assert user.full_name == "Owner Name"
    assert "TenantOwner" in user.realm_roles
    assert "UPDATE_PASSWORD" in user.actions_emailed


@pytest.mark.asyncio
async def test_create_tenant_marks_pending_provision_on_kc_failure(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    fake.fail_on = "ensure_group"
    service = get_tenant_service(admin_session, keycloak_client=fake)

    result = await service.create_tenant(
        slug=_slug("fail"),
        name="Will Fail",
        contact_email="ops@fail.test",
        owner_email="owner@fail.test",
        owner_full_name="Owner",
        actor_user_id=uuid4(),
    )

    assert result.status == "pending_provision"
    assert result.provisioning_failed is True
    assert result.owner_user_id is None

    snapshot = await service.get_tenant(result.tenant_id)
    assert snapshot.status == "pending_provision"
    assert snapshot.pending_owner_email == "owner@fail.test"
    assert snapshot.keycloak_group_id is None


@pytest.mark.asyncio
async def test_retry_provisioning_succeeds_after_failure(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    fake.fail_on = "ensure_group"
    service = get_tenant_service(admin_session, keycloak_client=fake)

    created = await service.create_tenant(
        slug=_slug("retry"),
        name="Retry",
        contact_email="ops@retry.test",
        owner_email="owner@retry.test",
        owner_full_name="Owner Retry",
        actor_user_id=uuid4(),
    )
    assert created.status == "pending_provision"

    # Retry: by now `fail_on` has been consumed, so subsequent calls work.
    snapshot = await service.retry_provisioning(created.tenant_id, actor_user_id=uuid4())
    assert snapshot.status == "active"
    assert snapshot.keycloak_group_id is not None
    assert snapshot.pending_owner_email is None
    assert len(fake.users) == 1


@pytest.mark.asyncio
async def test_retry_provisioning_rejects_active_tenant(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)
    created = await service.create_tenant(
        slug=_slug("act"),
        name="Active",
        contact_email="ops@act.test",
        actor_user_id=uuid4(),
    )
    with pytest.raises(InvalidStatusTransitionError):
        await service.retry_provisioning(created.tenant_id)


@pytest.mark.asyncio
async def test_retry_provisioning_without_pending_owner_raises(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)
    # Create without owner_email then manually flip status to pending_provision
    # to simulate a tenant whose pending_owner_* columns were cleared by hand.
    created = await service.create_tenant(
        slug=_slug("orph"),
        name="Orphan",
        contact_email="ops@orph.test",
        actor_user_id=uuid4(),
    )
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    await admin_session.execute(
        text("UPDATE public.tenants SET status='pending_provision' WHERE id = :tid").bindparams(
            bindparam("tid", type_=PG_UUID(as_uuid=True))
        ),
        {"tid": created.tenant_id},
    )

    with pytest.raises(NothingToProvisionError):
        await service.retry_provisioning(created.tenant_id)


@pytest.mark.asyncio
async def test_suspend_disables_keycloak_users_and_reactivate_enables(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)

    created = await service.create_tenant(
        slug=_slug("susp"),
        name="Susp",
        contact_email="ops@susp.test",
        owner_email="owner@susp.test",
        actor_user_id=uuid4(),
    )
    user_id = next(iter(fake.users))
    assert fake.users[user_id].enabled is True

    await service.suspend_tenant(created.tenant_id, actor_user_id=uuid4())
    assert fake.users[user_id].enabled is False

    await service.reactivate_tenant(created.tenant_id, actor_user_id=uuid4())
    assert fake.users[user_id].enabled is True


@pytest.mark.asyncio
async def test_purge_deletes_keycloak_group_and_users(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)

    created = await service.create_tenant(
        slug=_slug("prg"),
        name="Purge",
        contact_email="ops@prg.test",
        owner_email="owner@prg.test",
        actor_user_id=uuid4(),
    )
    assert len(fake.groups) == 1
    assert len(fake.users) == 1

    await service.request_delete(created.tenant_id, actor_user_id=uuid4())
    await service.purge_tenant(
        created.tenant_id,
        slug_confirmation=created.slug,
        force=True,
        actor_user_id=uuid4(),
    )

    assert len(fake.groups) == 0
    assert len(fake.users) == 0


@pytest.mark.asyncio
async def test_keycloak_failure_during_suspend_does_not_roll_back_db(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    service = get_tenant_service(admin_session, keycloak_client=fake)

    created = await service.create_tenant(
        slug=_slug("kcf"),
        name="KC Fail",
        contact_email="ops@kcf.test",
        owner_email="owner@kcf.test",
        actor_user_id=uuid4(),
    )

    fake.fail_on = "disable_users_in_group"
    snapshot = await service.suspend_tenant(created.tenant_id, actor_user_id=uuid4())
    # DB-side suspend went through even though KC threw.
    assert snapshot.status == "suspended"
