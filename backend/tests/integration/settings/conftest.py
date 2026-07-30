"""Shared fixtures for the platform-defaults endpoint tests.

Mirrors the per-package pattern used by the backfill/farms suites: mount
just this module's router on a fresh app behind a stubbed auth middleware,
so the capability dependency on each route is exercised end-to-end without
standing up Keycloak.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.platform_defaults.router import router as platform_defaults_router
from app.shared.auth.context import (
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)


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
    app.include_router(platform_defaults_router)
    app.add_middleware(StubAuth, context=context)
    return app


def make_context(
    *,
    user_id: UUID,
    tenant_id: UUID | None,
    tenant_role: TenantRole | None = None,
    platform_role: PlatformRole | None = None,
    farm_scopes: tuple[FarmScope, ...] = (),
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        platform_role=platform_role,
        farm_scopes=farm_scopes,
    )
