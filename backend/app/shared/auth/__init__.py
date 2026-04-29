"""Authentication primitives: JWT validation, RequestContext, middleware."""

from app.shared.auth.context import (
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)
from app.shared.auth.jwt import (
    InvalidTokenError,
    JWKSCache,
    JWTValidator,
    get_default_validator,
)
from app.shared.auth.middleware import AuthMiddleware, get_current_context

__all__ = [
    "AuthMiddleware",
    "FarmScope",
    "InvalidTokenError",
    "JWKSCache",
    "JWTValidator",
    "PlatformRole",
    "RequestContext",
    "TenantRole",
    "get_current_context",
    "get_default_validator",
]
