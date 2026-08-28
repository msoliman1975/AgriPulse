"""Fixed-window rate limiting on Redis.

The API had no rate limiter before the public trial routes, because every
other route needed a bearer token first. These routes need one.

A fixed window, not a sliding one: it costs a single INCR, the boundary
effect is harmless at these volumes, and a limiter nobody can reason about
is worse than one that lets through a few extra requests at a window edge.

Redis, not process memory: the API runs several replicas, and a per-process
counter would multiply every limit by the replica count.

**Redis being down does not block a request.** These limits protect a queue
and a mail sender, not data. Failing closed would take the whole signup form
offline for an outage in a cache, so the limiter fails open and says so in
the log.
"""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as redis_async

from app.core.logging import get_logger
from app.core.settings import get_settings

_log = get_logger(__name__)

_client: redis_async.Redis | None = None


def _get_client() -> redis_async.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis_async.Redis.from_url(str(settings.redis_url), decode_responses=True)
    return _client


def reset_client() -> None:
    """Drop the cached client. Tests call this after re-pointing settings."""
    global _client
    _client = None


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    used: int
    limit: int
    retry_after_seconds: int


async def check_and_increment(
    *,
    key: str,
    limit: int,
    window_seconds: int,
) -> LimitResult:
    """Count one hit against `key` and say whether it is allowed.

    The counter is created with its expiry in the same round trip, so a
    crash between INCR and EXPIRE cannot leave a key that never resets.
    """
    if limit <= 0:
        return LimitResult(allowed=True, used=0, limit=limit, retry_after_seconds=0)

    try:
        client = _get_client()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        used, _ = await pipe.execute()
        used = int(used)
        ttl = await client.ttl(key)
    except Exception as exc:
        _log.warning("ratelimit_unavailable", key=key, error=str(exc))
        return LimitResult(allowed=True, used=0, limit=limit, retry_after_seconds=0)

    return LimitResult(
        allowed=used <= limit,
        used=used,
        limit=limit,
        retry_after_seconds=max(int(ttl), 0),
    )
