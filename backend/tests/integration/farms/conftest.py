"""Shared fixtures for farms integration tests.

Each test that needs a tenant builds one through the tenancy service
(which bootstraps the schema and runs tenant migrations including the
new farms tables). The `_StubAuth` middleware then mounts the farms
router on a fresh FastAPI app with a hand-crafted RequestContext so
each test exercises the route path end-to-end without Keycloak.

`install_exception_handlers` is called on every test app so that
`APIError` instances raised by the routes turn into RFC 7807
problem+json responses (matching production wiring).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)


class StubAuth:
    """Minimal ASGI middleware that stamps a fixed RequestContext on the request.

    Mirrors the pattern used by `tests/integration/test_me_flow.py`.
    """

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
    """Mount only the farms router with a stubbed auth middleware."""
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
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


__all__ = [
    "ASGITransport",
    "AsyncClient",
    "FarmRole",
    "FarmScope",
    "PlatformRole",
    "StubAuth",
    "TenantRole",
    "build_app",
    "make_context",
]
