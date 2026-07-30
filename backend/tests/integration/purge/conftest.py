"""Fixtures for purge integration tests.

Mounts the purge router (and the farms router, needed to create the entities a
purge then removes) behind stubbed auth, matching the per-package pattern used
by the farms and backfill suites.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.purge.router import router as purge_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole, RequestContext, TenantRole


class StubAuth:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def build_app(context: RequestContext) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(purge_router)
    app.include_router(farms_router)
    app.add_middleware(StubAuth, context=context)
    return app


def make_context(
    *,
    user_id: UUID,
    tenant_id: UUID | None,
    tenant_role: TenantRole | None = None,
    platform_role: PlatformRole | None = None,
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        platform_role=platform_role,
    )


def client_for(context: RequestContext) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def square(lon: float, lat: float, side: float = 0.005) -> dict[str, Any]:
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


def polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + side, lat],
                [lon + side, lat + side],
                [lon, lat + side],
                [lon, lat],
            ]
        ],
    }


async def create_user_in_tenant(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> UUID:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": "Purge Test User",
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
    return membership_id


@pytest.fixture
async def tenant_env(admin_session: AsyncSession) -> dict[str, Any]:
    """A fresh tenant with a tenant-admin client and a platform-admin client."""
    slug = f"purge-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    membership_id = await create_user_in_tenant(
        admin_session, tenant_id=tenant.tenant_id, user_id=user_id
    )
    return {
        "tenant_id": tenant.tenant_id,
        "schema_name": tenant.schema_name,
        "slug": slug,
        "user_id": user_id,
        "membership_id": membership_id,
        "tenant_context": make_context(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            tenant_role=TenantRole.TENANT_ADMIN,
        ),
        "platform_context": make_context(
            user_id=uuid4(),
            tenant_id=None,
            platform_role=PlatformRole.PLATFORM_ADMIN,
        ),
    }
