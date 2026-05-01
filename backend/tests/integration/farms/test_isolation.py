"""Cross-tenant isolation: tenant A cannot read tenant B's farms."""

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


async def _bootstrap_user(session: AsyncSession, *, tenant_id, user_id, role: str) -> None:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": "U",
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
            "VALUES (:mid, :role)"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id, "role": role},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_user_in_tenant_a_cannot_read_tenant_b_farm(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    a = await tenancy.create_tenant(slug="iso-a", name="A", contact_email="ops@iso-a.test")
    b = await tenancy.create_tenant(slug="iso-b", name="B", contact_email="ops@iso-b.test")

    user_a = uuid4()
    user_b = uuid4()
    await _bootstrap_user(admin_session, tenant_id=a.tenant_id, user_id=user_a, role="TenantAdmin")
    await _bootstrap_user(admin_session, tenant_id=b.tenant_id, user_id=user_b, role="TenantAdmin")

    # B creates a farm; A tries to read it.
    ctx_b = make_context(
        user_id=user_b,
        tenant_id=b.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app_b = build_app(ctx_b)
    async with AsyncClient(transport=ASGITransport(app=app_b), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "BFARM-1",
                "name": "B's Farm",
                "boundary": _square(31.0, 30.0),
            },
        )
    assert resp.status_code == 201
    b_farm_id = resp.json()["id"]

    ctx_a = make_context(
        user_id=user_a,
        tenant_id=a.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app_a = build_app(ctx_a)
    async with AsyncClient(transport=ASGITransport(app=app_a), base_url="http://test") as c:
        resp = await c.get(f"/api/v1/farms/{b_farm_id}")
    assert resp.status_code == 404, "Cross-tenant read must return 404, never 403."

    # Direct SQL through tenant A's session also returns nothing.
    await admin_session.execute(text(f"SET LOCAL search_path TO {a.schema_name}, public"))
    count = (
        await admin_session.execute(
            text("SELECT count(*) FROM farms WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": b_farm_id},
        )
    ).scalar_one()
    assert count == 0
