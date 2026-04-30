"""Unit tests for the shared cursor pagination utility."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.shared.pagination import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)


def test_round_trip() -> None:
    for _ in range(20):
        u = uuid4()
        cursor = encode_cursor(u)
        decoded = decode_cursor(cursor)
        assert decoded == u


def test_decode_none_or_empty() -> None:
    assert decode_cursor(None) is None
    assert decode_cursor("") is None


def test_decode_rejects_garbage() -> None:
    # Truly-malformed base64 that survives padding into something the wrong
    # length — the cursor decoder rejects it as either invalid encoding or
    # invalid length depending on how Python's b64decode tolerates it.
    with pytest.raises(ValueError, match=r"invalid cursor (encoding|length)"):
        decode_cursor("not-a-base64-string!!")


def test_decode_rejects_bad_version() -> None:
    # Replace version byte 0x01 with 0xFF (unsupported).
    import base64

    raw = bytes((0xFF,)) + UUID(int=1).bytes
    bogus = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    with pytest.raises(ValueError, match="unsupported cursor version"):
        decode_cursor(bogus)


def test_decode_rejects_short_payload() -> None:
    import base64

    bogus = base64.urlsafe_b64encode(bytes((0x01, 0x02, 0x03))).decode("ascii").rstrip("=")
    with pytest.raises(ValueError, match="invalid cursor length"):
        decode_cursor(bogus)


def test_clamp_limit_defaults() -> None:
    assert clamp_limit(None) == DEFAULT_PAGE_LIMIT
    assert clamp_limit(0) == DEFAULT_PAGE_LIMIT
    assert clamp_limit(-5) == DEFAULT_PAGE_LIMIT


def test_clamp_limit_caps() -> None:
    assert clamp_limit(MAX_PAGE_LIMIT + 100) == MAX_PAGE_LIMIT


def test_clamp_limit_passthrough() -> None:
    assert clamp_limit(75) == 75
