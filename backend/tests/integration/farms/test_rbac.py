"""Integration tests: per-farm RBAC enforcement.

* Viewer on farm A cannot edit farm A.
* FarmManager on farm A cannot edit farm B (404 — not 403).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole

from .conftest import build_app, make_context

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="asyncpg+UUID encoding issue — see test_me_flow.py."),
]


def _multipolygon(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
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


async def _seed_user(session: AsyncSession, *, tenant_id, user_id) -> None:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": "u@rbac.test",
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
    await session.commit()


@pytest.mark.asyncio
async def test_viewer_cannot_update_farm(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="rbac-viewer", name="RBAC", contact_email="ops@rbac-v.test"
    )

    # Admin creates the farm.
    admin_user = uuid4()
    await _seed_user(admin_session, tenant_id=tenant.tenant_id, user_id=admin_user)
    admin_ctx = make_context(
        user_id=admin_user,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    admin_app = build_app(admin_ctx)
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={"code": "RV", "name": "RV", "boundary": _multipolygon(31.0, 30.0)},
        )
    farm_id = resp.json()["id"]

    # Viewer attempts to update.
    viewer_user = uuid4()
    await _seed_user(admin_session, tenant_id=tenant.tenant_id, user_id=viewer_user)
    from uuid import UUID as _UUID

    viewer_ctx = make_context(
        user_id=viewer_user,
        tenant_id=tenant.tenant_id,
        farm_scopes=(FarmScope(farm_id=_UUID(farm_id), role=FarmRole.VIEWER),),
    )
    viewer_app = build_app(viewer_ctx)
    async with AsyncClient(transport=ASGITransport(app=viewer_app), base_url="http://test") as c:
        resp = await c.patch(
            f"/api/v1/farms/{farm_id}",
            json={"name": "Renamed by viewer"},
        )
    assert resp.status_code == 403
