"""Cursor-based pagination envelope for list endpoints.

Cursors are opaque to clients but encode the trailing UUID v7 of the
last-returned item plus a tiny version/format byte for forward-
compatibility. Because UUID v7 sorts chronologically, a cursor on `id`
gives stable, monotonic pagination without introducing a separate sort
column.

Usage in a router:

    from app.shared.pagination import CursorPage, decode_cursor, encode_cursor

    rows = await repo.list_after(after=decode_cursor(cursor), limit=limit)
    next_cursor = encode_cursor(rows[-1].id) if len(rows) == limit else None
    return CursorPage[FarmResponse](items=rows, next_cursor=next_cursor)
"""

from __future__ import annotations

import base64
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")

# Format prefix: 1 byte (currently 0x01) + 16 raw UUID bytes, base64url-encoded.
# Future revisions can bump the byte to evolve the cursor without breaking
# clients that round-trip an opaque string.
_CURSOR_VERSION = 0x01


class CursorPage(BaseModel, Generic[T]):
    """Generic paginated response envelope.

    `next_cursor` is `None` when there is no further page. `items` holds
    at most `limit` entries, in `id ASC` order — UUID v7 makes this
    equivalent to oldest-first chronological order.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[T]
    next_cursor: str | None = None


def encode_cursor(last_id: UUID) -> str:
    """Encode a UUID into an opaque cursor string."""
    payload = bytes((_CURSOR_VERSION,)) + last_id.bytes
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> UUID | None:
    """Decode a client-supplied cursor; return None if absent.

    Raises ValueError on a malformed or unsupported-version cursor so
    callers can map it to a 422 with a translatable message key.
    """
    if cursor is None or cursor == "":
        return None
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise ValueError("invalid cursor encoding") from exc
    if len(raw) != 17:
        raise ValueError("invalid cursor length")
    if raw[0] != _CURSOR_VERSION:
        raise ValueError(f"unsupported cursor version: {raw[0]}")
    return UUID(bytes=raw[1:])


# Default page size and hard cap — used by routers that accept ?limit=.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def clamp_limit(raw: int | None) -> int:
    """Apply the default and the cap. Negative or zero values fall back to default."""
    if raw is None or raw <= 0:
        return DEFAULT_PAGE_LIMIT
    return min(raw, MAX_PAGE_LIMIT)
