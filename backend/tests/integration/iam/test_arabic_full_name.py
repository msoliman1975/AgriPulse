"""`users.full_name_ar` survives the one thing that overwrites `full_name`.

Public migration 0076 added the column. The reason it is a separate column
rather than a translation of `full_name` is that `upsert_from_jwt` copies the
name out of the Keycloak token on every sign-in. Anything written into
`full_name` by the tenant is replaced the next time that person logs in.

So the test that matters is the last one: sign in after setting the Arabic
name, and the Arabic name is still there. Without it, this feature would look
correct in every screenshot and quietly erase itself on the person's next
login — the slowest possible way to find out.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.iam.service import UserServiceImpl
from app.modules.iam.users_service import TenantUsersService
from app.modules.tenancy.service import get_tenant_service
from app.shared.keycloak import FakeKeycloakClient

pytestmark = [pytest.mark.integration]

NAME_AR = "أحمد فتحي"
NAME_AR_2 = "أحمد فتحي عبد الله"


async def _tenant(admin_session: AsyncSession, fake: FakeKeycloakClient) -> tuple[str, str]:
    slug = f"ar-name-{uuid4().hex[:8]}"
    result = await get_tenant_service(admin_session, keycloak_client=fake).create_tenant(
        slug=slug,
        name=f"Tenant {slug}",
        contact_email=f"ops@{slug}.test",
        actor_user_id=None,
    )
    return result.tenant_id, result.schema_name


@pytest.mark.asyncio
async def test_invite_stores_the_arabic_name_and_the_list_returns_it(
    admin_session: AsyncSession,
) -> None:
    fake = FakeKeycloakClient()
    tenant_id, schema = await _tenant(admin_session, fake)
    svc = TenantUsersService(public_session=admin_session, keycloak=fake)

    await svc.invite_user(
        email="ahmed@ar-name.test",
        full_name="Ahmed Fathy",
        full_name_ar=NAME_AR,
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    rows = await svc.list_users(tenant_id=tenant_id)
    assert len(rows) == 1
    assert rows[0]["full_name"] == "Ahmed Fathy"
    assert rows[0]["full_name_ar"] == NAME_AR


@pytest.mark.asyncio
async def test_omitting_the_arabic_name_stores_null(admin_session: AsyncSession) -> None:
    """Nothing copies the English name in, unlike every other Arabic column.

    A person's name in Latin script already reads inside an Arabic sentence.
    Copying it would make an unauthored name indistinguishable from a real
    one, so nobody could tell which rows still need attention.
    """
    fake = FakeKeycloakClient()
    tenant_id, schema = await _tenant(admin_session, fake)
    svc = TenantUsersService(public_session=admin_session, keycloak=fake)

    await svc.invite_user(
        email="english@ar-name.test",
        full_name="English Only",
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )

    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["full_name_ar"] is None


@pytest.mark.asyncio
async def test_patch_accepts_the_arabic_name(admin_session: AsyncSession) -> None:
    """`update_user` filters through a static allowlist.

    A key missing from it is dropped without an error, so the PATCH returns
    200 and the value never changes — which reads as "the save did nothing".
    """
    fake = FakeKeycloakClient()
    tenant_id, schema = await _tenant(admin_session, fake)
    svc = TenantUsersService(public_session=admin_session, keycloak=fake)

    await svc.invite_user(
        email="patch@ar-name.test",
        full_name="Patch Me",
        full_name_ar=NAME_AR,
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    user_id = (await svc.list_users(tenant_id=tenant_id))[0]["id"]

    await svc.update_user(
        user_id=user_id,
        tenant_id=tenant_id,
        updates={"full_name_ar": NAME_AR_2},
        preferences_patch=None,
        actor_user_id=None,
        tenant_schema=schema,
    )

    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["full_name_ar"] == NAME_AR_2
    # An Arabic-only edit leaves the English name alone.
    assert rows[0]["full_name"] == "Patch Me"


@pytest.mark.asyncio
async def test_signing_in_does_not_erase_the_arabic_name(
    admin_session: AsyncSession,
) -> None:
    """The whole reason the column exists.

    `get_me` runs `upsert_from_jwt`, which writes `full_name` from the token.
    If that statement ever touched `full_name_ar`, the Arabic name would be
    replaced by the token's Latin name at the person's next sign-in.
    """
    fake = FakeKeycloakClient()
    tenant_id, schema = await _tenant(admin_session, fake)
    svc = TenantUsersService(public_session=admin_session, keycloak=fake)

    await svc.invite_user(
        email="login@ar-name.test",
        full_name="Login Person",
        full_name_ar=NAME_AR,
        phone=None,
        tenant_role="TenantAdmin",
        tenant_schema=schema,
        actor_user_id=None,
    )
    user_id = (await svc.list_users(tenant_id=tenant_id))[0]["id"]

    me = await UserServiceImpl(admin_session).get_me(
        user_id,
        email="login@ar-name.test",
        full_name="Login Person",
    )

    assert me.full_name_ar == NAME_AR
    rows = await svc.list_users(tenant_id=tenant_id)
    assert rows[0]["full_name_ar"] == NAME_AR
