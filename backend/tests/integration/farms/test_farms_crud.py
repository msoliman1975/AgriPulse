"""Integration tests for farm CRUD endpoints."""

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

pytestmark = [pytest.mark.integration]


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [lon, lat],
                    [lon + side, lat],
                    [lon + side, lat + side],
                    [lon, lat + side],
                    [lon, lat],
                ]
            ]
        ],
    }


async def _create_user_in_tenant(session: AsyncSession, *, tenant_id, user_id) -> None:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": "Test User",
        },
    )
    membership_id = uuid4()
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
    await session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_create_and_get_farm(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-crud-1",
        name="Farms CRUD",
        contact_email="ops@farms-crud.test",
    )

    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-1",
                "name": "Acme Farm 1",
                "boundary": _square(31.2, 30.0),
                "farm_type": "commercial",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "FARM-1"
    assert body["is_active"] is True
    assert body["active_to"] is None
    assert body["area_unit"] == "feddan"
    assert float(body["area_value"]) > 0
    farm_id = body["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/v1/farms/{farm_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == farm_id


@pytest.mark.asyncio
async def test_create_rejects_out_of_egypt_geometry(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-bbox",
        name="OOB",
        contact_email="ops@farms-bbox.test",
    )

    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-OOB",
                "name": "Out of bounds",
                # Tripoli — outside Egypt's bbox.
                "boundary": _square(13.0, 32.0),
                "farm_type": "commercial",
            },
        )
    assert resp.status_code == 422
    assert "Egypt" in resp.json().get("title", "") or "egypt" in resp.text.lower()


@pytest.mark.asyncio
async def test_archive_then_get_returns_404(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-archive",
        name="Archive",
        contact_email="ops@farms-archive.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-A",
                "name": "Will Archive",
                "boundary": _square(31.2, 30.0),
            },
        )
        farm_id = resp.json()["id"]

        del_resp = await c.delete(f"/api/v1/farms/{farm_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["farm_id"] == farm_id
        assert del_resp.json()["block_count"] == 0

        get_resp = await c.get(f"/api/v1/farms/{farm_id}")
        assert get_resp.status_code == 404
