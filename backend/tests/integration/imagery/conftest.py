"""Shared fixtures for imagery integration tests.

Mirrors the farms-conftest pattern: each test boots a tenant via
`tenancy.create_tenant`, mounts a fresh FastAPI app with the imagery
router and a stubbed auth middleware, and hits the routes through an
`httpx.AsyncClient`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.imagery.router import router as imagery_router
from app.modules.indices.router import router as indices_router
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)


class StubAuth:
    """Pin a fixed RequestContext on every request, no JWT validation."""

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
    """Mount imagery + farms (for fixture creation through the API) routers."""
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(imagery_router)
    app.include_router(indices_router)
    app.add_middleware(StubAuth, context=context)
    return app


def make_context(
    *,
    user_id: UUID,
    tenant_id: UUID | None,
    tenant_role: TenantRole | None = None,
    platform_role: PlatformRole | None = None,
    farm_scopes: tuple[FarmScope, ...] = (),
    preferred_unit: str = "feddan",
    preferred_language: str = "en",
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        platform_role=platform_role,
        farm_scopes=farm_scopes,
        preferred_language=preferred_language,  # type: ignore[arg-type]
        preferred_unit=preferred_unit,  # type: ignore[arg-type]
    )


async def create_user_in_tenant(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID,
    tenant_role: str = "TenantAdmin",
) -> None:
    """Insert a user + tenant membership + role for testing."""
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
            "VALUES (:mid, :role)"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id, "role": tenant_role},
    )
    await session.commit()


__all__ = [
    "ASGITransport",
    "AsyncClient",
    "FarmRole",
    "FarmScope",
    "PlatformRole",
    "StubAuth",
    "TenantRole",
    "build_app",
    "create_user_in_tenant",
    "make_context",
]
