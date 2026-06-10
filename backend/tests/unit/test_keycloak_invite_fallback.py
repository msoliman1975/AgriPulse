"""IH-2: SMTP-independent invite fallback contract.

Exercised against ``FakeKeycloakClient`` (the same surface the services
depend on) so the behavior is verifiable without a live Keycloak: when
SMTP is unavailable the invite mints a one-time temporary password
instead of emailing the reset link, and ``resend_invite`` re-issues a
credential on demand.
"""

from __future__ import annotations

import pytest

from app.shared.keycloak.client import InviteResult
from app.shared.keycloak.fakes import FakeKeycloakClient


@pytest.mark.asyncio
async def test_invite_user_emails_when_smtp_enabled() -> None:
    fake = FakeKeycloakClient()  # smtp_enabled defaults True
    group_id = await fake.ensure_group("acme")

    result = await fake.invite_user(
        email="owner@acme.test",
        full_name="Owner",
        group_id=group_id,
        roles=("TenantOwner",),
        tenant_id="11111111-1111-1111-1111-111111111111",
    )

    assert isinstance(result, InviteResult)
    assert result.email_sent is True
    assert result.temporary_password is None
    user = fake.users[result.keycloak_user_id]
    assert "UPDATE_PASSWORD" in user.actions_emailed


@pytest.mark.asyncio
async def test_invite_user_mints_temp_password_when_smtp_disabled() -> None:
    fake = FakeKeycloakClient()
    fake.smtp_enabled = False
    group_id = await fake.ensure_group("acme")

    result = await fake.invite_user(
        email="owner@acme.test",
        full_name="Owner",
        group_id=group_id,
        roles=("TenantOwner",),
        tenant_id="11111111-1111-1111-1111-111111111111",
    )

    assert result.email_sent is False
    assert result.temporary_password is not None
    assert fake.users[result.keycloak_user_id].temporary_password == result.temporary_password


@pytest.mark.asyncio
async def test_invite_platform_admin_respects_smtp_flag() -> None:
    fake = FakeKeycloakClient()
    fake.smtp_enabled = False

    result = await fake.invite_platform_admin(
        email="staff@agripulse.test", full_name="Staff", role="PlatformAdmin"
    )

    assert result.email_sent is False
    assert result.temporary_password is not None
    assert fake.users[result.keycloak_user_id].platform_role == "PlatformAdmin"


@pytest.mark.asyncio
async def test_resend_invite_reissues_credential() -> None:
    fake = FakeKeycloakClient()
    group_id = await fake.ensure_group("acme")
    invited = await fake.invite_user(
        email="owner@acme.test",
        full_name="Owner",
        group_id=group_id,
        tenant_id="11111111-1111-1111-1111-111111111111",
    )

    # SMTP goes down before the resend — caller gets a temp password.
    fake.smtp_enabled = False
    resent = await fake.resend_invite(keycloak_user_id=invited.keycloak_user_id)

    assert resent.keycloak_user_id == invited.keycloak_user_id
    assert resent.email_sent is False
    assert resent.temporary_password is not None


@pytest.mark.asyncio
async def test_resend_invite_unknown_user_raises() -> None:
    from app.shared.keycloak.errors import KeycloakRequestError

    fake = FakeKeycloakClient()
    with pytest.raises(KeycloakRequestError):
        await fake.resend_invite(keycloak_user_id="does-not-exist")
