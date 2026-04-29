"""FastAPI middleware that validates the bearer JWT and builds RequestContext.

Bypassed paths (no auth required, no 401 raised):
  - /health         (liveness probe)
  - /metrics        (separate listener; defense-in-depth bypass here too)
  - /docs, /redoc, /openapi.json  (debug-mode only; app_factory disables
    them in production)

Every other path requires a valid Bearer JWT. Failures surface as 401
with an RFC 7807 problem+json body — handled in app.core.errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import HTTPException, Request, status
from structlog.contextvars import bind_contextvars, unbind_contextvars

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.auth.jwt import InvalidTokenError, JWTValidator, get_default_validator

if TYPE_CHECKING:
    from collections.abc import Iterable

    from starlette.types import ASGIApp


_PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}
)
_PUBLIC_PREFIXES: tuple[str, ...] = ("/docs/oauth2-redirect",)


def _is_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _claim_uuid(claims: dict[str, Any], key: str) -> UUID | None:
    raw = claims.get(key)
    if raw is None:
        return None
    return UUID(str(raw))


def _build_context(claims: dict[str, Any]) -> RequestContext:
    """Construct a RequestContext from validated claims.

    Unknown role values are dropped silently; the resulting context will
    just lack the bad field. RBAC checks fall through to a 403 in that
    case, which is the desired behavior.
    """
    user_id = _claim_uuid(claims, "sub")
    if user_id is None:
        raise InvalidTokenError("Token claims missing 'sub'")

    tenant_id = _claim_uuid(claims, "tenant_id")

    tenant_role = _safe_enum(claims.get("tenant_role"), TenantRole)
    platform_role = _safe_enum(claims.get("platform_role"), PlatformRole)

    farm_scopes = tuple(_iter_farm_scopes(claims.get("farm_scopes") or []))

    preferred_language = claims.get("preferred_language", "en")
    if preferred_language not in ("en", "ar"):
        preferred_language = "en"

    preferred_unit = claims.get("preferred_unit", "feddan")
    if preferred_unit not in ("feddan", "acre", "hectare"):
        preferred_unit = "feddan"

    return RequestContext(
        user_id=user_id,
        keycloak_subject=str(claims.get("sub")),
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        platform_role=platform_role,
        farm_scopes=farm_scopes,
        preferred_language=preferred_language,
        preferred_unit=preferred_unit,
    )


def _iter_farm_scopes(items: Iterable[Any]) -> Iterable[FarmScope]:
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            farm_id = UUID(str(item["farm_id"]))
        except (KeyError, ValueError):
            continue
        role = _safe_enum(item.get("role"), FarmRole)
        if role is None:
            continue
        yield FarmScope(farm_id=farm_id, role=role)


def _safe_enum[E](value: object, enum_cls: type[E]) -> E | None:
    if value is None:
        return None
    try:
        return enum_cls(value)  # type: ignore[call-arg]
    except (ValueError, TypeError):
        return None


class AuthMiddleware:
    """Pure ASGI middleware so it can short-circuit before BaseHTTPMiddleware overhead.

    Validates Bearer tokens and attaches RequestContext to scope.state.
    """

    def __init__(self, app: ASGIApp, validator: JWTValidator | None = None) -> None:
        self._app = app
        self._validator = validator

    @property
    def validator(self) -> JWTValidator:
        return self._validator or get_default_validator()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if _is_public(path):
            await self._app(scope, receive, send)
            return

        # Build a Request to access headers without consuming the body.
        request = Request(scope, receive=receive)

        token = _extract_bearer_token(request)
        if token is None:
            await _send_unauthorized(send, "Missing bearer token")
            return

        log = get_logger(__name__)
        try:
            claims = self.validator.validate(token)
            context = _build_context(claims)
        except InvalidTokenError as exc:
            log.info("auth_invalid_token", reason=str(exc), path=path)
            await _send_unauthorized(send, str(exc))
            return

        scope.setdefault("state", {})
        # Starlette uses scope["state"] dict; FastAPI surfaces it as request.state.
        # Either way these names are stable contracts other code reads.
        request.state.context = context
        request.state.tenant_schema = context.tenant_schema
        request.state.user_id = context.user_id
        request.state.tenant_id = context.tenant_id

        bind_contextvars(
            user_id=str(context.user_id),
            tenant_id=str(context.tenant_id) if context.tenant_id else None,
        )
        try:
            await self._app(scope, receive, send)
        finally:
            unbind_contextvars("user_id", "tenant_id")


def _extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    scheme, _, value = auth.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


async def _send_unauthorized(send: Any, detail: str) -> None:
    """Send a 401 problem+json body."""
    import json

    body = {
        "type": "https://missionagre.io/problems/unauthorized",
        "title": "Unauthorized",
        "status": 401,
        "detail": detail,
    }
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"www-authenticate", b'Bearer realm="missionagre"'),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


def get_current_context(request: Request) -> RequestContext:
    """FastAPI dependency: return the RequestContext for the current request.

    Routes that don't already 401 via the middleware are guaranteed to
    have a context attached. If for any reason it's missing, raise 401.
    """
    context = getattr(request.state, "context", None)
    if context is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return context


# Suppress an unused-import warning when running with strict mypy.
_ = get_settings
