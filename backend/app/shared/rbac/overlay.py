"""Per-process cache of the runtime RBAC overrides.

`role_capabilities.yaml` is the reviewed baseline and is compiled once into
`CapabilityRegistry`. A Platform Admin can layer *deltas* on top of it at
runtime (`public.rbac_role_capability_overrides`); this module is how those
deltas reach the authorization path without a DB round-trip per request.

Shape, and why each part is the way it is:

  - `current()` is **synchronous** and pure memory. `role_grants` calls it on
    every capability check, so it must not be a coroutine — making it one would
    change all 255 `requires_capability` sites and the 75 imperative
    `has_capability` callers, for a lookup that is two dict `.get()`s.
  - `ensure_fresh()` is the async half, awaited **once per request** from
    `AuthMiddleware.__call__` right beside the tenant-status lookup that
    already happens there. The common path is a `monotonic()` compare.
  - The snapshot is pre-materialised as `dict[role][capability] -> bool`, so a
    check never builds a merged set. This is the hot path.

This is `auth/tenant_status.py`'s TTL/lock/fail-soft structure composed with
`settings/resolver.py`'s `invalidate()` hook — both already carry this design
in production. Copied deliberately rather than reinvented.

Staleness is bounded by `TTL_SECONDS`: the writing pod is at 0s (its write
path calls `refresh()`), every other pod within 30s. For context, tenant
suspension already accepts 30s, platform defaults 60s, and JWT farm-scope
revocation fifteen minutes.

**Constraint:** import-linter forbids `app.shared.*` from importing
`app.modules.*`, so this module uses raw `text()` over `AsyncSessionLocal` and
cannot reach the audit module. Change recording lives in the router instead.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import get_logger
from app.shared.db.session import AsyncSessionLocal

#: Upper bound on how long a policy change takes to reach a pod that did not
#: make it. Public because the admin API sends it to the UI — the number an
#: admin is promised has to be the one the cache actually uses.
TTL_SECONDS: float = 30.0

#: PlatformAdmin holds the literal `"*"` wildcard, and an override against it
#: could revoke `platform.manage_rbac` (or `platform.manage_tenants`, which the
#: frontend's PlatformAdminGuard gates on) and lock every admin out of the
#: surface that would undo it. Rows naming it are dropped **here, at load**, so
#: even a row inserted straight into the database by hand cannot take effect.
#: The write API refuses them too — two independent places, on purpose.
IMMUTABLE_ROLES: frozenset[str] = frozenset({"PlatformAdmin"})

_OVERRIDES_SQL = text(
    """
    SELECT role, capability, granted
      FROM public.rbac_role_capability_overrides
    """
)

# role -> capability -> granted
Snapshot = Mapping[str, Mapping[str, bool]]

_snapshot: dict[str, dict[str, bool]] = {}
_loaded_at: float | None = None
_lock = asyncio.Lock()


def current() -> Snapshot:
    """The overrides in memory. Synchronous, allocation-free, never blocks.

    Empty until the first successful load, which means the YAML baseline
    applies — the safe default, since that is the reviewed policy.
    """
    return _snapshot


def _is_fresh(now: float) -> bool:
    return _loaded_at is not None and (now - _loaded_at) < TTL_SECONDS


async def ensure_fresh() -> None:
    """Reload the overrides if the cached copy has aged out.

    Awaited once per request from the auth middleware. Cheap on the common
    path: one `monotonic()` read and a compare.
    """
    if _is_fresh(time.monotonic()):
        return

    async with _lock:
        # Double-checked under the lock — a concurrent request may have just
        # refreshed, and a thundering herd on the auth path is exactly what
        # this cache exists to prevent.
        if _is_fresh(time.monotonic()):
            return
        await _load()


async def refresh() -> None:
    """Force a reload, ignoring the TTL. Called from the write path.

    Makes an admin's own change effective in their pod immediately, so the
    matrix they re-read after saving reflects what they just did.
    """
    async with _lock:
        await _load()


def invalidate() -> None:
    """Mark the snapshot stale so the next `ensure_fresh()` reloads.

    The synchronous counterpart to `refresh()`, mirroring
    `settings.resolver.invalidate_defaults_cache()`.
    """
    global _loaded_at
    _loaded_at = None


def clear_cache() -> None:
    """Test hook — drop the snapshot and the load timestamp."""
    global _loaded_at
    _snapshot.clear()
    _loaded_at = None


def set_snapshot_for_test(snapshot: Mapping[str, Mapping[str, bool]]) -> None:
    """Test hook — install a snapshot without a database.

    Marks it fresh so `ensure_fresh()` will not immediately overwrite it.
    """
    global _loaded_at
    _snapshot.clear()
    _snapshot.update({role: dict(caps) for role, caps in snapshot.items()})
    _loaded_at = time.monotonic()


async def _load() -> None:
    """Replace the snapshot from the database. Must be called under `_lock`."""
    global _loaded_at
    log = get_logger(__name__)
    factory = AsyncSessionLocal()
    try:
        async with factory() as session:
            rows = (await session.execute(_OVERRIDES_SQL)).all()
    except SQLAlchemyError as exc:
        # Fail soft, in both senses. A DB blip must not 500 a request on the
        # auth path, and a pod whose code is ahead of migration 0056 (the table
        # does not exist yet) must still serve — in both cases the last good
        # snapshot stands, or the baseline if there has never been one.
        #
        # `_loaded_at` is still stamped so a database that is down is retried
        # once per TTL rather than once per request.
        _loaded_at = time.monotonic()
        log.warning("rbac_overlay_load_failed", error=str(exc))
        return

    fresh: dict[str, dict[str, bool]] = {}
    for row in rows:
        role = str(row.role)
        if role in IMMUTABLE_ROLES:
            # Defence in depth — see IMMUTABLE_ROLES. Loud, because a row here
            # means either the write API's guard was bypassed or someone
            # reached for psql.
            log.warning(
                "rbac_overlay_ignored_immutable_role",
                role=role,
                capability=str(row.capability),
            )
            continue
        fresh.setdefault(role, {})[str(row.capability)] = bool(row.granted)

    # Swap in place rather than rebinding: `current()` hands out this dict and
    # callers may hold the reference across the swap.
    _snapshot.clear()
    _snapshot.update(fresh)
    _loaded_at = time.monotonic()
