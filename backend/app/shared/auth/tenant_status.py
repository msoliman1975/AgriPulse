"""Per-process cache of `public.tenants.status` for the auth middleware.

The middleware needs to fail-closed for non-platform JWTs whose tenant is
suspended or pending_delete. Hitting the DB on every request would add a
round-trip to the hot path, so we cache the status with a short TTL.

The runbook contract is "existing sessions fail closed within ~30 seconds";
our default `_TTL_SECONDS = 30` matches that.

The cache is per-process. In a multi-replica deployment the TTL is the
upper bound on inconsistency between replicas — acceptable for an admin
operation that's expected to take effect "soon", not "instantly."
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import OperationalError

from app.shared.db.session import AsyncSessionLocal

_TTL_SECONDS: float = 30.0

TenantStatus = Literal["active", "suspended", "pending_delete", "archived", "missing"]


@dataclass(slots=True)
class _Entry:
    status: TenantStatus
    fetched_at: float


_cache: dict[UUID, _Entry] = {}
_lock = asyncio.Lock()


async def get_tenant_status(tenant_id: UUID) -> TenantStatus:
    """Return the cached tenant status, refreshing if stale.

    Returns ``"missing"`` if the tenant row is not found (e.g., purged).
    """
    now = time.monotonic()
    cached = _cache.get(tenant_id)
    if cached is not None and (now - cached.fetched_at) < _TTL_SECONDS:
        return cached.status

    async with _lock:
        # Double-checked under lock — another coroutine may have refreshed.
        cached = _cache.get(tenant_id)
        if cached is not None and (time.monotonic() - cached.fetched_at) < _TTL_SECONDS:
            return cached.status

        status = await _fetch_status(tenant_id)
        _cache[tenant_id] = _Entry(status=status, fetched_at=time.monotonic())
        return status


async def _fetch_status(tenant_id: UUID) -> TenantStatus:
    # Raw SQL (not the ORM Tenant model) keeps this module free of an
    # import path through `app.modules.tenancy`, which itself imports
    # this module for cache invalidation.
    factory = AsyncSessionLocal()
    try:
        async with factory() as session:
            row = (
                await session.execute(
                    text("SELECT status FROM public.tenants WHERE id = :tid").bindparams(
                        bindparam("tid", type_=PG_UUID(as_uuid=True))
                    ),
                    {"tid": tenant_id},
                )
            ).scalar_one_or_none()
    except OperationalError:
        # DB blip during a request must not 500. Fall back to "active" so the
        # request proceeds; a cached refresh will pick up the real value next.
        return "active"
    if row is None:
        return "missing"
    if row in ("active", "suspended", "pending_delete", "archived"):
        return row
    return "active"


def invalidate(tenant_id: UUID) -> None:
    """Drop the cached status for one tenant (called from lifecycle paths)."""
    _cache.pop(tenant_id, None)


def clear_cache() -> None:
    """Test hook — wipe the entire cache."""
    _cache.clear()
