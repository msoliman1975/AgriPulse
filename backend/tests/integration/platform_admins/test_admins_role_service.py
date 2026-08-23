"""Integration tests for `PlatformAdminsRoleService` provisioning repair.

The bug these cover: when Keycloak refuses the invite (it was down, or the
`agripulse-tenancy` client secret drifted from the one the api holds), the
invite still writes the DB rows and parks the user at
`keycloak_subject = 'pending::<email>'`. Before this change nothing ever
retried:

  * re-inviting the same person hit the 409 "already a platform admin"
    branch, so the Keycloak call never ran again;
  * the branch that talks to Keycloak for an existing global user was
    guarded on the subject NOT being a `pending::` stub.

So the row kept the "(pending Keycloak provisioning)" badge for ever and
the person could never sign in.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_admins.admins_service import (
    PlatformAdminNotFoundError,
    PlatformAdminProvisioningError,
    PlatformAdminsRoleService,
)
from app.shared.keycloak import FakeKeycloakClient

pytestmark = [pytest.mark.integration]


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}@example.test"


def _service(admin_session: AsyncSession, fake: FakeKeycloakClient) -> PlatformAdminsRoleService:
    return PlatformAdminsRoleService(public_session=admin_session, keycloak=fake)


async def _subject(admin_session: AsyncSession, user_id: UUID) -> str | None:
    row = (
        await admin_session.execute(
            text("SELECT keycloak_subject FROM public.users WHERE id = :uid").bindparams(
                bindparam("uid", type_=PG_UUID(as_uuid=True))
            ),
            {"uid": user_id},
        )
    ).first()
    return None if row is None else row.keycloak_subject


async def _invite_with_keycloak_down(
    admin_session: AsyncSession,
    fake: FakeKeycloakClient,
    *,
    email: str,
    role: str = "PlatformAdmin",
) -> dict[str, Any]:
    fake.fail_on = "invite_platform_admin"
    result = await _service(admin_session, fake).invite_admin(
        email=email,
        full_name="Stuck Admin",
        role=role,
        actor_user_id=None,
    )
    assert result["keycloak_provisioning"] == "pending"
    return result


async def test_invite_parks_at_pending_when_keycloak_refuses(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    email = _email("pending")

    result = await _invite_with_keycloak_down(admin_session, fake, email=email)

    assert await _subject(admin_session, result["user_id"]) == f"pending::{email}"
    assert not any(u.email == email for u in fake.users.values())


async def test_retry_provisioning_repairs_a_pending_row(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    email = _email("retry")
    invited = await _invite_with_keycloak_down(admin_session, fake, email=email)

    # Keycloak is healthy again.
    retried = await _service(admin_session, fake).retry_provisioning(
        user_id=invited["user_id"],
        role="PlatformAdmin",
        actor_user_id=None,
    )

    assert retried["keycloak_provisioning"] == "succeeded"
    kc_user = next(u for u in fake.users.values() if u.email == email)
    assert kc_user.platform_role == "PlatformAdmin"
    assert "PlatformAdmin" in kc_user.realm_roles
    # The DB row now carries the real subject, so the UI badge clears.
    subject = await _subject(admin_session, invited["user_id"])
    assert subject == kc_user.id
    assert subject is not None
    assert not subject.startswith("pending::")


async def test_retry_provisioning_surfaces_a_keycloak_failure(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    email = _email("still-down")
    invited = await _invite_with_keycloak_down(admin_session, fake, email=email)

    fake.fail_on = "invite_platform_admin"
    with pytest.raises(PlatformAdminProvisioningError):
        await _service(admin_session, fake).retry_provisioning(
            user_id=invited["user_id"],
            role="PlatformAdmin",
            actor_user_id=None,
        )

    # Still pending — no half-written subject.
    assert await _subject(admin_session, invited["user_id"]) == f"pending::{email}"


async def test_retry_provisioning_on_a_non_admin_raises_not_found(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    with pytest.raises(PlatformAdminNotFoundError):
        await _service(admin_session, fake).retry_provisioning(
            user_id=uuid4(),
            role="PlatformAdmin",
            actor_user_id=None,
        )


async def test_retry_provisioning_is_idempotent_for_an_already_provisioned_admin(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    email = _email("healthy")
    invited = await _service(admin_session, fake).invite_admin(
        email=email,
        full_name="Healthy Admin",
        role="PlatformAdmin",
        actor_user_id=None,
    )
    assert invited["keycloak_provisioning"] == "succeeded"
    before = await _subject(admin_session, invited["user_id"])

    retried = await _service(admin_session, fake).retry_provisioning(
        user_id=invited["user_id"],
        role="PlatformAdmin",
        actor_user_id=None,
    )

    assert retried["keycloak_provisioning"] == "succeeded"
    assert await _subject(admin_session, invited["user_id"]) == before
    assert len([u for u in fake.users.values() if u.email == email]) == 1


async def test_second_invite_of_a_pending_user_retries_keycloak(
    admin_session: AsyncSession,
) -> None:
    """A different role for the same stuck person must not stay pending."""
    fake = FakeKeycloakClient()
    email = _email("second-role")
    invited = await _invite_with_keycloak_down(admin_session, fake, email=email)

    second = await _service(admin_session, fake).invite_admin(
        email=email,
        full_name="Stuck Admin",
        role="PlatformSupport",
        actor_user_id=None,
    )

    assert second["user_id"] == invited["user_id"]
    assert second["keycloak_provisioning"] == "succeeded"
    subject = await _subject(admin_session, invited["user_id"])
    assert subject is not None
    assert not subject.startswith("pending::")
