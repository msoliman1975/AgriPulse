"""Per-block integration health tolerates blocks with no name.

`blocks.name` is nullable and bulk AOI upload creates blocks from a file
name (code only), so a farm can legitimately be full of nameless blocks.
The response model declared `block_name: str`, which turned every such
farm into a 500 — raised inside the streaming response, so the CORS
headers were already gone and the browser reported it as a CORS failure
rather than a server error.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.integrations_health.router import router as health_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import RequestContext, TenantRole
from tests.integration.farms.conftest import StubAuth, make_context

pytestmark = [pytest.mark.integration]


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    ring = [
        [lon, lat],
        [lon + side, lat],
        [lon + side, lat + side],
        [lon, lat + side],
        [lon, lat],
    ]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def _square_polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
    ring = [
        [lon, lat],
        [lon + side, lat],
        [lon + side, lat + side],
        [lon, lat + side],
        [lon, lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _build_app(context: RequestContext) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(health_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _create_user_in_tenant(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> None:
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
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": uuid4(), "uid": user_id, "tid": tenant_id},
    )


@pytest.mark.asyncio
async def test_block_health_falls_back_to_code_when_unnamed(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="ih-unnamed",
        name="ih-unnamed",
        contact_email="ops@ih-unnamed.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        # No "name" — exactly what bulk AOI upload used to create.
        unnamed = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "NONAME", "boundary": _square_polygon(31.201, 30.001)},
        )
        assert unnamed.status_code == 201, unnamed.text
        assert unnamed.json()["name"] is None
        named = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "NAMED", "name": "North", "boundary": _square_polygon(31.203, 30.001)},
        )
        assert named.status_code == 201, named.text

        resp = await c.get(f"/api/v1/integrations/health/farms/{farm_id}/blocks")
        assert resp.status_code == 200, resp.text
        by_id = {r["block_id"]: r["block_name"] for r in resp.json()}
        assert by_id[unnamed.json()["id"]] == "NONAME"  # falls back to the code
        assert by_id[named.json()["id"]] == "North"
