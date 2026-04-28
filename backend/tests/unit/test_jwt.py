"""Unit tests for the JWKS cache and JWT validator.

The validator's signature/expiry checks rely on `python-jose`; rather
than re-test the library, we cover the parts we own: the cache's
refresh-on-miss-or-TTL behavior and the validator's error mapping.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.shared.auth.jwt import InvalidTokenError, JWKSCache, JWTValidator


def _fake_client(payload: dict[str, Any]) -> httpx.Client:
    client = MagicMock(spec=httpx.Client)
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    client.get.return_value = response
    client.close.return_value = None
    return client


def test_jwks_cache_returns_key_by_kid() -> None:
    payload = {
        "keys": [
            {"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"},
            {"kid": "k2", "kty": "RSA", "n": "y", "e": "AQAB"},
        ]
    }
    cache = JWKSCache("https://kc/jwks", ttl_seconds=3600, http_client=_fake_client(payload))
    assert cache.get_key("k1")["n"] == "x"
    assert cache.get_key("k2")["n"] == "y"


def test_jwks_cache_refreshes_on_unknown_kid() -> None:
    first = {"keys": [{"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"}]}
    rotated = {
        "keys": [
            {"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"},
            {"kid": "k2", "kty": "RSA", "n": "y", "e": "AQAB"},
        ]
    }
    client = MagicMock(spec=httpx.Client)
    response_first = MagicMock()
    response_first.json.return_value = first
    response_first.raise_for_status.return_value = None
    response_rotated = MagicMock()
    response_rotated.json.return_value = rotated
    response_rotated.raise_for_status.return_value = None
    client.get.side_effect = [response_first, response_rotated]
    client.close.return_value = None

    cache = JWKSCache("https://kc/jwks", ttl_seconds=3600, http_client=client)
    # First call hits k1; cache is populated.
    assert cache.get_key("k1")["n"] == "x"
    # Asking for k2 forces a refresh that surfaces the rotated keyset.
    assert cache.get_key("k2")["n"] == "y"
    assert client.get.call_count == 2


def test_jwks_cache_raises_when_key_still_missing_after_refresh() -> None:
    payload = {"keys": [{"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"}]}
    cache = JWKSCache("https://kc/jwks", ttl_seconds=3600, http_client=_fake_client(payload))
    with pytest.raises(InvalidTokenError, match="Unknown signing key"):
        cache.get_key("ghost")


def test_jwks_cache_raises_on_empty_jwks() -> None:
    cache = JWKSCache(
        "https://kc/jwks", ttl_seconds=3600, http_client=_fake_client({"keys": []})
    )
    with pytest.raises(InvalidTokenError, match="JWKS is empty"):
        cache.get_key("anything")


def test_validator_rejects_token_without_kid_header() -> None:
    cache = JWKSCache(
        "https://kc/jwks",
        ttl_seconds=3600,
        http_client=_fake_client({"keys": [{"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"}]}),
    )
    validator = JWTValidator(
        issuer="https://kc/realms/r", audience="api", jwks_cache=cache
    )
    # A garbage string fails before we ever look up the key — we just
    # care that any failure is wrapped as InvalidTokenError.
    with pytest.raises(InvalidTokenError):
        validator.validate("not-a-jwt")
