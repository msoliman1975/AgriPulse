"""Integration test: GET /api/v1/me end-to-end against a live Postgres.

Auth is *not* exercised here — we mount the iam router on a minimal app
that pre-populates `request.state.context` so the route runs as if the
JWT had already been validated. Real Keycloak token validation is
covered by a separate Keycloak-container test in a later prompt.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.iam.router import router as iam_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)

pytestmark = [pytest.mark.integration]


class _StubAuth:
    """Tiny ASGI middleware: stamp a fixed RequestContext on request.state."""

    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def _build_app(context: RequestContext) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(iam_router)
    app.add_middleware(_StubAuth, context=context)
    return app


@pytest.mark.asyncio
async def test_me_returns_profile_preferences_memberships_scopes(
    admin_session: AsyncSession,
) -> None:
    # Create a tenant, a user, link them, grant a tenant role + a farm scope.
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="me-flow-test",
        name="Me Flow Tenant",
        contact_email="ops@me-flow.test",
    )

    user_id = uuid4()
    await admin_session.execute(
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
    await admin_session.execute(
        text(
            "INSERT INTO public.user_preferences (user_id, language, unit_system) "
            "VALUES (:id, 'ar', 'acre')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id},
    )
    membership_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant.tenant_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    farm_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.farm_scopes (membership_id, farm_id, role) "
            "VALUES (:mid, :fid, 'FarmManager')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "fid": farm_id},
    )
    await admin_session.commit()

    context = RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
        farm_scopes=(FarmScope(farm_id=farm_id, role=FarmRole.FARM_MANAGER),),
    )

    app = _build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/me")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(user_id)
    assert body["full_name"] == "Test User"
    assert body["preferences"]["language"] == "ar"
    assert body["preferences"]["unit_system"] == "acre"

    memberships = body["tenant_memberships"]
    assert len(memberships) == 1
    assert memberships[0]["tenant_slug"] == "me-flow-test"
    assert any(r["role"] == "TenantAdmin" for r in memberships[0]["tenant_roles"])

    scopes = body["farm_scopes"]
    assert len(scopes) == 1
    assert scopes[0]["farm_id"] == str(farm_id)
    assert scopes[0]["role"] == "FarmManager"


@pytest.mark.asyncio
async def test_me_returns_404_for_unknown_user() -> None:
    context = RequestContext(
        user_id=uuid4(),
        keycloak_subject="kc-ghost",
        tenant_id=uuid4(),
        platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    app = _build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/me")
    assert resp.status_code == 404
