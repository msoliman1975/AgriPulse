"""Shared fixtures for weather integration tests.

Mirrors the imagery conftest: each test boots a tenant via
`tenancy.create_tenant`, mounts a fresh FastAPI app with the weather +
farms routers and a stubbed auth middleware, and hits the routes
through an `httpx.AsyncClient`.
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
from app.modules.weather.router import router as weather_router
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
    """Mount weather + farms (for fixture creation) routers."""
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(weather_router)
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


def square_polygon(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    """A small square polygon for block boundaries."""
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


def multipoly(lon: float, lat: float, side: float = 0.01) -> dict[str, object]:
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


async def create_farm_and_block(client: AsyncClient, *, slug: str = "1") -> tuple[str, str]:
    """Create a farm + block via the farms router, return (farm_id, block_id)."""
    resp = await client.post(
        "/api/v1/farms",
        json={
            "code": f"FARM-WX-{slug}",
            "name": f"Weather Test Farm {slug}",
            "boundary": multipoly(31.2, 30.0),
            "farm_type": "commercial",
            "tags": [],
        },
    )
    assert resp.status_code == 201, resp.text
    farm_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={
            "code": f"B-WX-{slug}",
            "boundary": square_polygon(31.21, 30.01),
        },
    )
    assert resp.status_code == 201, resp.text
    block_id = resp.json()["id"]
    return farm_id, block_id


__all__ = [
    "ASGITransport",
    "AsyncClient",
    "FarmRole",
    "FarmScope",
    "PlatformRole",
    "StubAuth",
    "TenantRole",
    "build_app",
    "create_farm_and_block",
    "create_user_in_tenant",
    "make_context",
    "multipoly",
    "square_polygon",
]
