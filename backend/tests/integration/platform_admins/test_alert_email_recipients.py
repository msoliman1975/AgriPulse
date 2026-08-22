"""Who receives the platform-alert digest.

The checkbox on `/platform/admins` and the recipient query the sweep runs
are two halves of one contract, and they live in different modules. These
tests run both against the real table so they cannot drift apart silently.
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
    PlatformAdminsRoleService,
)
from app.modules.platform_alerts.repository import PlatformAlertsRepository

pytestmark = [pytest.mark.integration]

_UID = bindparam("uid", type_=PG_UUID(as_uuid=True))


async def _seed_admin(
    session: AsyncSession, *, email: str, roles: tuple[str, ...] = ("PlatformAdmin",)
) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.users (id, email, full_name, keycloak_subject) "
            "VALUES (:uid, :email, :name, :kc)"
        ).bindparams(_UID),
        # `keycloak_subject` is NOT NULL. The invite flow writes a
        # `pending::` placeholder when Keycloak has not answered yet, so
        # that is the shape a real row can hold.
        {
            "uid": user_id,
            "email": email,
            "name": "Ops Person",
            "kc": f"pending::{user_id}",
        },
    )
    for role in roles:
        await session.execute(
            text(
                "INSERT INTO public.platform_role_assignments (user_id, role) "
                "VALUES (:uid, :role)"
            ).bindparams(_UID),
            {"uid": user_id, "role": role},
        )
    await session.commit()
    return user_id


def _service(session: AsyncSession) -> PlatformAdminsRoleService:
    # No Keycloak: this setting never touches it. Passing a sentinel keeps
    # the test from reaching for a client it must not use.
    return PlatformAdminsRoleService(public_session=session, keycloak=object())  # type: ignore[arg-type]


async def _emails(session: AsyncSession) -> list[str]:
    rows = await PlatformAlertsRepository(session).list_email_recipients()
    return [r["email"] for r in rows]


@pytest.mark.asyncio
async def test_nobody_receives_until_the_box_is_ticked(admin_session: AsyncSession) -> None:
    """Default off. Turning the feature on must not start mailing people
    who never asked for it."""
    email = f"quiet-{uuid4().hex[:8]}@example.test"
    await _seed_admin(admin_session, email=email)

    assert email not in await _emails(admin_session)


@pytest.mark.asyncio
async def test_ticking_the_box_adds_the_address(admin_session: AsyncSession) -> None:
    email = f"oncall-{uuid4().hex[:8]}@example.test"
    user_id = await _seed_admin(admin_session, email=email)

    await _service(admin_session).set_alert_emails(
        user_id=user_id, role="PlatformAdmin", enabled=True, actor_user_id=None
    )
    await admin_session.commit()

    assert email in await _emails(admin_session)

    await _service(admin_session).set_alert_emails(
        user_id=user_id, role="PlatformAdmin", enabled=False, actor_user_id=None
    )
    await admin_session.commit()

    assert email not in await _emails(admin_session)


@pytest.mark.asyncio
async def test_two_roles_is_still_one_email(admin_session: AsyncSession) -> None:
    """A person can hold PlatformAdmin and PlatformSupport, which is two
    grant rows. Without DISTINCT they would get the digest twice."""
    email = f"both-{uuid4().hex[:8]}@example.test"
    user_id = await _seed_admin(
        admin_session, email=email, roles=("PlatformAdmin", "PlatformSupport")
    )

    svc = _service(admin_session)
    for role in ("PlatformAdmin", "PlatformSupport"):
        await svc.set_alert_emails(user_id=user_id, role=role, enabled=True, actor_user_id=None)
    await admin_session.commit()

    assert (await _emails(admin_session)).count(email) == 1


@pytest.mark.asyncio
async def test_list_admins_reports_the_flag(admin_session: AsyncSession) -> None:
    """The page renders the checkbox from this read, so it has to carry it."""
    email = f"listed-{uuid4().hex[:8]}@example.test"
    user_id = await _seed_admin(admin_session, email=email)
    await _service(admin_session).set_alert_emails(
        user_id=user_id, role="PlatformAdmin", enabled=True, actor_user_id=None
    )
    await admin_session.commit()

    rows: list[dict[str, Any]] = await _service(admin_session).list_admins()
    mine = [r for r in rows if r["email"] == email]
    assert len(mine) == 1
    assert mine[0]["receives_alert_emails"] is True


@pytest.mark.asyncio
async def test_unknown_grant_is_a_404_not_a_silent_no_op(
    admin_session: AsyncSession,
) -> None:
    """An UPDATE that matches nothing returns success from Postgres. The
    operator would tick a box, see it snap back, and have nothing to read."""
    with pytest.raises(PlatformAdminNotFoundError):
        await _service(admin_session).set_alert_emails(
            user_id=uuid4(), role="PlatformAdmin", enabled=True, actor_user_id=None
        )
