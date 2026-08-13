"""Tenant purge must not leave unreachable ``public.users`` rows behind.

``public.users`` carries no ownership column, so it is not — and cannot be — a
manifest entry: a user is reachable *from* a tenant via ``tenant_memberships``,
possibly from several. Every tenant purge before this therefore left the users
whose only membership was in the purged tenant sitting in ``public.users``,
holding their unique email against any future invite. That residue is what
forced the ``SMOKE_EMAIL_SUFFIX`` workaround in ``scripts/e2e/provision_demo.py``.

The set removed is deliberately narrow, and three of these tests exist to pin
the boundaries of it rather than the happy path: a user with a surviving
membership elsewhere stays, and a platform admin stays even with no membership
at all.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.keycloak import FakeKeycloakClient
from app.shared.purge.scanner import scan_public

pytestmark = [pytest.mark.integration]

_UID = bindparam("uid", type_=PG_UUID(as_uuid=True))
_TID = bindparam("tid", type_=PG_UUID(as_uuid=True))


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


async def _create(session: AsyncSession):
    service = get_tenant_service(session, keycloak_client=FakeKeycloakClient())
    return await service.create_tenant(
        slug=_slug("orph"),
        name="Orphan Test",
        contact_email="ops@orph.test",
        actor_user_id=uuid4(),
    )


async def _purge(session: AsyncSession, tenant_id: UUID, slug: str) -> None:
    service = get_tenant_service(session, keycloak_client=FakeKeycloakClient())
    await service.request_delete(tenant_id, actor_user_id=uuid4())
    await service.purge_tenant(tenant_id, slug_confirmation=slug, force=True, actor_user_id=uuid4())


async def _add_user(
    session: AsyncSession, *, tenant_id: UUID, invited_by: UUID | None = None
) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:uid, :sub, :email, 'Orphan Test User')"
        ).bindparams(_UID),
        {"uid": user_id, "sub": f"kc-{user_id}", "email": f"u-{user_id}@orph.test"},
    )
    await _add_membership(session, user_id=user_id, tenant_id=tenant_id, invited_by=invited_by)
    return user_id


async def _add_membership(
    session: AsyncSession, *, user_id: UUID, tenant_id: UUID, invited_by: UUID | None = None
) -> UUID:
    membership_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status, invited_by) "
            "VALUES (:mid, :uid, :tid, 'active', :inv)"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            _UID,
            _TID,
            bindparam("inv", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant_id, "inv": invited_by},
    )
    return membership_id


async def _user_exists(session: AsyncSession, user_id: UUID) -> bool:
    return bool(
        (
            await session.execute(
                text("SELECT 1 FROM public.users WHERE id = :uid").bindparams(_UID),
                {"uid": user_id},
            )
        ).scalar_one_or_none()
    )


@pytest.mark.asyncio
async def test_purge_removes_users_left_with_no_membership(admin_session: AsyncSession) -> None:
    tenant = await _create(admin_session)
    user_id = await _add_user(admin_session, tenant_id=tenant.tenant_id)
    await admin_session.commit()

    await _purge(admin_session, tenant.tenant_id, tenant.slug)

    assert not await _user_exists(admin_session, user_id)


@pytest.mark.asyncio
async def test_purge_keeps_user_with_membership_in_another_tenant(
    admin_session: AsyncSession,
) -> None:
    """The reason this cannot be a blanket delete of the tenant's members."""
    doomed = await _create(admin_session)
    survivor = await _create(admin_session)
    user_id = await _add_user(admin_session, tenant_id=doomed.tenant_id)
    await _add_membership(admin_session, user_id=user_id, tenant_id=survivor.tenant_id)
    await admin_session.commit()

    await _purge(admin_session, doomed.tenant_id, doomed.slug)

    assert await _user_exists(admin_session, user_id)


@pytest.mark.asyncio
async def test_purge_keeps_platform_admin_with_no_membership(
    admin_session: AsyncSession,
) -> None:
    """A platform admin routinely has no tenant membership.

    Deleting one because the last tenant it happened to touch was purged would
    lock an operator out of the platform entirely.
    """
    tenant = await _create(admin_session)
    user_id = await _add_user(admin_session, tenant_id=tenant.tenant_id)
    await admin_session.execute(
        text(
            "INSERT INTO public.platform_role_assignments (user_id, role) "
            "VALUES (:uid, 'PlatformAdmin')"
        ).bindparams(_UID),
        {"uid": user_id},
    )
    await admin_session.commit()

    await _purge(admin_session, tenant.tenant_id, tenant.slug)

    assert await _user_exists(admin_session, user_id)


@pytest.mark.asyncio
async def test_purge_survives_provenance_reference_from_another_tenant(
    admin_session: AsyncSession,
) -> None:
    """``invited_by`` has no ON DELETE, so an unblanked reference aborts the purge.

    The inviter is purged; the person they invited lives in a tenant that
    survives. Without nulling the provenance first, the DELETE raises a foreign
    key violation and the whole purge rolls back.
    """
    doomed = await _create(admin_session)
    survivor = await _create(admin_session)
    inviter = await _add_user(admin_session, tenant_id=doomed.tenant_id)
    invitee = await _add_user(admin_session, tenant_id=survivor.tenant_id, invited_by=inviter)
    await admin_session.commit()

    await _purge(admin_session, doomed.tenant_id, doomed.slug)

    assert not await _user_exists(admin_session, inviter)
    assert await _user_exists(admin_session, invitee)
    remaining = (
        await admin_session.execute(
            text(
                "SELECT invited_by FROM public.tenant_memberships WHERE user_id = :uid"
            ).bindparams(_UID),
            {"uid": invitee},
        )
    ).scalar_one()
    assert remaining is None


@pytest.mark.asyncio
async def test_scanner_reports_unreachable_users(admin_session: AsyncSession) -> None:
    """The verify-clean signal the harness reads after a purge.

    ``GET /admin/purge/orphans`` is built on this scan, so a user left with no
    route to it has to show up as an orphan or the check proves nothing.
    """
    user_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:uid, :sub, :email, 'Stranded User')"
        ).bindparams(_UID),
        {"uid": user_id, "sub": f"kc-{user_id}", "email": f"u-{user_id}@orph.test"},
    )
    await admin_session.commit()

    result = await scan_public(admin_session)

    users_orphan = next((o for o in result.orphans if o.table == "users"), None)
    assert users_orphan is not None
    assert users_orphan.rows >= 1
