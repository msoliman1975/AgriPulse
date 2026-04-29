"""Keycloak JWT validation backed by a cached JWKS.

JWKS is fetched from `Settings.keycloak_jwks_url` on first use and cached
in-process for `keycloak_jwks_cache_ttl_seconds` (default 1 hour).

Validation steps:
  1. Decode JWS header to find `kid`
  2. Resolve the matching key in the cached JWKS (refresh on miss)
  3. python-jose verifies signature, expiry, issuer, and audience

Errors map to InvalidTokenError; the middleware converts that to a 401.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError
from jose.utils import base64url_decode

from app.core.settings import Settings, get_settings


class InvalidTokenError(Exception):
    """Raised when a JWT fails validation. Middleware translates to 401."""


@dataclass(slots=True)
class _CachedJwks:
    keys_by_kid: dict[str, dict[str, Any]]
    fetched_at: float


class JWKSCache:
    """In-process cache of Keycloak's JWKS, refreshed on miss or TTL expiry."""

    def __init__(self, jwks_url: str, ttl_seconds: int, http_client: httpx.Client | None = None):
        self._jwks_url = jwks_url
        self._ttl = ttl_seconds
        self._client = http_client
        self._cached: _CachedJwks | None = None
        self._lock = threading.Lock()

    def _client_or_default(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=5.0)

    def _refresh(self) -> _CachedJwks:
        client = self._client_or_default()
        try:
            response = client.get(self._jwks_url)
            response.raise_for_status()
            payload = response.json()
        finally:
            if self._client is None:
                client.close()

        keys = payload.get("keys", [])
        if not keys:
            raise InvalidTokenError("JWKS is empty")
        keys_by_kid = {k["kid"]: k for k in keys if "kid" in k}
        cached = _CachedJwks(keys_by_kid=keys_by_kid, fetched_at=time.monotonic())
        self._cached = cached
        return cached

    def _is_fresh(self, cached: _CachedJwks) -> bool:
        return (time.monotonic() - cached.fetched_at) < self._ttl

    def get_key(self, kid: str) -> dict[str, Any]:
        """Return the JWKS entry for `kid`, refreshing on miss or TTL expiry."""
        with self._lock:
            cached = self._cached
            if cached is None or not self._is_fresh(cached):
                cached = self._refresh()
            if kid not in cached.keys_by_kid:
                # Possible key rotation; force a refresh.
                cached = self._refresh()
            if kid not in cached.keys_by_kid:
                raise InvalidTokenError(f"Unknown signing key: kid={kid}")
            return cached.keys_by_kid[kid]

    def clear(self) -> None:
        """Drop the cache. Used in tests."""
        with self._lock:
            self._cached = None


class JWTValidator:
    """Stateless validator that uses a JWKSCache to verify tokens."""

    def __init__(self, *, issuer: str, audience: str, jwks_cache: JWKSCache) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks_cache = jwks_cache

    def validate(self, token: str) -> dict[str, Any]:
        """Return the verified claims dict, or raise InvalidTokenError.

        Validates: signature, expiry (`exp`), not-before (`nbf`), issuer
        (`iss`), audience (`aud`). Issued-at (`iat`) is required by
        Keycloak; python-jose enforces it implicitly when `exp` is
        compared.
        """
        try:
            unverified_header = jose_jwt.get_unverified_header(token)
        except JWTError as exc:
            raise InvalidTokenError(f"Malformed token header: {exc}") from exc

        kid = unverified_header.get("kid")
        if not kid:
            raise InvalidTokenError("Token header missing 'kid'")

        key = self._jwks_cache.get_key(kid)

        try:
            claims = jose_jwt.decode(
                token,
                key,
                algorithms=[unverified_header.get("alg", "RS256")],
                audience=self._audience,
                issuer=self._issuer,
                options={"verify_at_hash": False},
            )
        except ExpiredSignatureError as exc:
            raise InvalidTokenError("Token has expired") from exc
        except JWTClaimsError as exc:
            raise InvalidTokenError(f"Token claim invalid: {exc}") from exc
        except JWTError as exc:
            raise InvalidTokenError(f"Token signature invalid: {exc}") from exc

        return claims


_default_validator: JWTValidator | None = None
_default_validator_lock = threading.Lock()


def get_default_validator(settings: Settings | None = None) -> JWTValidator:
    """Return the process-wide JWTValidator, building it on first call."""
    global _default_validator
    with _default_validator_lock:
        if _default_validator is None:
            cfg = settings or get_settings()
            cache = JWKSCache(cfg.keycloak_jwks_url, cfg.keycloak_jwks_cache_ttl_seconds)
            _default_validator = JWTValidator(
                issuer=cfg.keycloak_issuer,
                audience=cfg.keycloak_audience,
                jwks_cache=cache,
            )
        return _default_validator


def reset_default_validator() -> None:
    """Drop the process-wide validator. Used in tests."""
    global _default_validator
    with _default_validator_lock:
        _default_validator = None


# Helper used by tests: decode a JWT segment without verification.
def unverified_payload(token: str) -> dict[str, Any]:
    """Return the JWT payload without verification. **Test use only.**"""
    parts = token.split(".")
    if len(parts) < 2:
        raise InvalidTokenError("Token does not contain a payload segment")
    import json

    return json.loads(base64url_decode(parts[1].encode()).decode())
