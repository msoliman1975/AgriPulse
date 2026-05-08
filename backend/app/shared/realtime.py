"""Real-time push for the in-app inbox.

A thin wrapper around Redis pub/sub. Two flavors:

  * **Sync publisher** — used by the notifications subscriber, which
    runs in a synchronous handler off the event bus.
  * **Async subscriber** — used by the FastAPI SSE endpoint, which
    needs to yield events as they arrive without blocking its event
    loop.

Channel naming: ``inbox:<tenant_id>:<user_id>``. Scoping by tenant_id
prevents a user with the same UUID across tenants (extremely unlikely,
but possible) from leaking events. Payloads are JSON-encoded strings;
Redis handles the rest.

Why pub/sub and not Streams: we don't need persistence. If a user is
offline, the in-app inbox row in Postgres is the source of truth; the
push is best-effort. SSE clients call ``GET /api/v1/inbox`` on
reconnect to catch up.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import redis as redis_sync
import redis.asyncio as redis_async

from app.core.logging import get_logger
from app.core.settings import get_settings

_log = get_logger(__name__)

_sync_client: redis_sync.Redis | None = None


def _channel(tenant_id: UUID, user_id: UUID) -> str:
    return f"inbox:{tenant_id}:{user_id}"


def _get_sync_client() -> redis_sync.Redis:
    """Lazy singleton — the publish path is hot, but we still only need one."""
    global _sync_client
    if _sync_client is None:
        settings = get_settings()
        _sync_client = redis_sync.Redis.from_url(str(settings.redis_url), decode_responses=True)
    return _sync_client


def publish_to_user(*, tenant_id: UUID, user_id: UUID, payload: dict[str, Any]) -> None:
    """Best-effort publish to the user's channel.

    Failures are logged and swallowed — Redis going away mustn't break
    the publishing transaction. The Postgres-backed inbox row is the
    durable record.
    """
    try:
        client = _get_sync_client()
        client.publish(_channel(tenant_id, user_id), json.dumps(payload, default=str))
    except Exception as exc:
        _log.warning(
            "realtime_publish_failed",
            channel=_channel(tenant_id, user_id),
            error=str(exc),
        )


async def subscribe(
    *,
    tenant_id: UUID,
    user_id: UUID,
    keepalive_seconds: float = 30.0,
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings for events on the user's channel.

    Yields ``: keepalive\\n\\n`` comment lines every ``keepalive_seconds``
    so any intermediary proxy keeps the connection open. Caller is
    responsible for the surrounding ``StreamingResponse``.

    The async generator unsubscribes and closes the client when the
    consumer stops iterating — typical FastAPI behavior on client
    disconnect.
    """
    settings = get_settings()
    client = redis_async.Redis.from_url(str(settings.redis_url), decode_responses=True)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    channel = _channel(tenant_id, user_id)
    try:
        await pubsub.subscribe(channel)
        # Initial comment so curl-style clients see something immediately.
        yield ": connected\n\n"
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(timeout=keepalive_seconds),
                    timeout=keepalive_seconds + 1.0,
                )
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if message is None:
                yield ": keepalive\n\n"
                continue
            data = message.get("data")
            if not isinstance(data, str):
                continue
            yield f"event: inbox\ndata: {data}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        finally:
            await client.aclose()
