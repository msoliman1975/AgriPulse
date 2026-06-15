"""U-4a: FarmResponse.farm_manager is derived from the FarmManager scope.

The stored farm_manager_id column was dropped (tenant migration 0045). The
farm's manager is now resolved read-only from the active FarmManager
farm-scope with the earliest grant. Covers: no manager -> null; assigned
manager -> {membership_id, full_name}; resolution on both the detail and
list endpoints.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


async def _add_named_member(session: AsyncSession, *, tenant_id, full_name: str):
    """Insert a user + active membership with a known name; return its id."""
    user_id = uuid4()
    membership_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": full_name,
        },
    )
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant_id},
    )
    await session.commit()
    return membership_id


@pytest.mark.asyncio
async def test_farm_manager_derived_from_scope(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farm-mgr-derive",
        name="Farm Mgr Derive",
        contact_email="ops@farm-mgr.test",
    )
    actor_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=actor_id)
    context = make_context(
        user_id=actor_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        created = await c.post(
            "/api/v1/farms",
            json={
                "code": "FM-HAS",
                "name": "Managed",
                "boundary": _square(31.3, 30.1),
                "farm_type": "commercial",
            },
        )
        assert created.status_code == 201, created.text
        farm_id = created.json()["id"]
        # Brand-new farm has no manager.
        assert created.json()["farm_manager"] is None

    membership_id = await _add_named_member(
        admin_session, tenant_id=tenant.tenant_id, full_name="Salma Manager"
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assign = await c.post(
            f"/api/v1/farms/{farm_id}/members",
            json={"membership_id": str(membership_id), "role": "FarmManager"},
        )
        assert assign.status_code in (200, 201), assign.text

        # Detail endpoint resolves the derived manager.
        got = await c.get(f"/api/v1/farms/{farm_id}")
        assert got.status_code == 200, got.text
        manager = got.json()["farm_manager"]
        assert manager is not None
        assert manager["membership_id"] == str(membership_id)
        assert manager["full_name"] == "Salma Manager"

        # List endpoint resolves it too (batched).
        listed = await c.get("/api/v1/farms")
        assert listed.status_code == 200, listed.text
        by_id = {f["id"]: f for f in listed.json()["items"]}
        assert by_id[farm_id]["farm_manager"]["membership_id"] == str(membership_id)
