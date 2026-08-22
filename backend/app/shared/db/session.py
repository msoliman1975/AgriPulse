"""Async SQLAlchemy session management with tenant-aware search_path.

Two FastAPI dependencies:

  * `get_db_session(request)` — returns a session pinned to
    `tenant_<id>, public` if the request has a tenant context (set by
    the auth middleware), or `public` only if it does not. Use this for
    tenant-scoped routes.

  * `get_admin_db_session()` — returns a session pinned to `public` only.
    Use this for platform-admin routes that intentionally bypass tenant
    context (e.g., POST /api/v1/admin/tenants).

Both wrap `AsyncSessionLocal()` in a transaction. `SET LOCAL search_path`
is used so the change is automatically rolled back at end of transaction.

Tenant schema name is validated via `sanitize_tenant_schema` to prevent
SQL injection through the JWT claim.
"""

# NOTE: deliberately NO `from __future__ import annotations`. The
# `get_db_session` dependency below uses `request: Request`, and FastAPI
# can't resolve string annotations to the FastAPI Request injection —
# it would silently demote the parameter to a query param.

import asyncio
import re
import threading
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from app.core.logging import get_logger
from app.core.settings import get_settings

_log = get_logger(__name__)

# Public name kept for typing in module imports.
Engine = AsyncEngine

_engine: AsyncEngine | None = None
# The event loop the current engine's pool belongs to, or None if it has not
# been used inside one yet. An asyncpg connection is owned by the loop that
# opened it, so an engine outlives its loop only as a trap. See `get_engine`.
_engine_loop: asyncio.AbstractEventLoop | None = None
_engine_lock = threading.Lock()
_TENANT_SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]{1,64}$")


def sanitize_tenant_schema(schema_name: str) -> str:
    """Return `schema_name` if it is a valid tenant schema name, else raise.

    Tenant schemas are the only thing we interpolate into SQL, so this
    validation function is the gatekeeper. The pattern matches the
    `schema_name` column shape on `public.tenants` (data_model § 3.2).
    """
    if not _TENANT_SCHEMA_RE.fullmatch(schema_name):
        raise ValueError(f"Invalid tenant schema name: {schema_name!r}")
    return schema_name


def create_engine() -> AsyncEngine:
    """Build a fresh async engine using current Settings.

    Production code should call `get_engine()` to reuse the singleton.
    Tests may call this directly when they need an isolated engine.

    `prepared_statement_cache_size=0` disables asyncpg's per-connection
    statement cache. With caching, asyncpg occasionally serializes UUID
    parameters via the un-padded hex of `uuid.int` (a known interaction
    with SQLAlchemy 2.x's parameter rebinding) which Postgres rejects
    as "invalid input syntax for type uuid". Cost is minor — Postgres
    parses each statement once instead of caching. Revisit if profiling
    shows it as hot.
    """
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        echo=settings.database_echo,
        future=True,
        connect_args={"prepared_statement_cache_size": 0},
    )


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call.

    An engine whose pool belongs to a different event loop is abandoned and
    rebuilt rather than handed out.

    Celery workers are synchronous, so every task body opens its own loop
    with `asyncio.run`. Each task is supposed to dispose the engine before
    that loop closes; two of them did not, and the next task in the same
    worker process inherited pooled asyncpg connections owned by a loop that
    no longer existed. Every query it ran raised "got Future attached to a
    different loop", and because the failure was in the pool rather than in
    the task, the four tasks that reported it were never the ones at fault.

    Fixing the two call sites removes today's instance. This check is what
    stops the next one: a task that forgets to dispose now costs one
    abandoned pool, not a worker process that fails every job it is given
    until it restarts.

    The old engine is dropped, not closed. Closing it means awaiting on the
    dead loop, which is the exact thing that raises. The sockets go when the
    object is collected.
    """
    global _engine, _engine_loop
    loop = _running_loop()
    with _engine_lock:
        if _engine is not None and loop is not None:
            if _engine_loop is None:
                # Built outside a loop and used inside this one first.
                # Nothing has connected yet, so it belongs here now.
                _engine_loop = loop
            elif _engine_loop is not loop:
                _log.warning(
                    "db_engine_abandoned_foreign_loop",
                    reason="a task closed its event loop without disposing the engine",
                )
                _engine = None
                _engine_loop = None
        if _engine is None:
            _engine = create_engine()
            _engine_loop = loop
        return _engine


async def dispose_engine() -> None:
    """Dispose the process-wide engine. Used in app shutdown and tests.

    The global is cleared even when `dispose()` raises. Disposing a pool
    whose asyncpg connections were created on an event loop that has since
    closed can itself fail, and leaving the broken engine installed turns
    one bad task into every later task in that worker process failing the
    same way, for the life of the process. Dropping the reference is what
    lets the next `get_engine()` build a clean one.
    """
    global _engine, _engine_loop
    loop = _running_loop()
    with _engine_lock:
        engine, engine_loop = _engine, _engine_loop
        _engine, _engine_loop = None, None
    if engine is None:
        return
    if engine_loop is not None and loop is not None and engine_loop is not loop:
        # Disposing means awaiting the pool's connections closed, and those
        # belong to a loop that is not this one. Awaiting them here raises
        # the same different-loop error we are trying to prevent. The
        # reference is already dropped, which is what matters.
        _log.warning("db_engine_dispose_skipped_foreign_loop")
        return
    await engine.dispose()


def AsyncSessionLocal() -> async_sessionmaker[AsyncSession]:
    """Session factory. Lower-cased call sites match SQLAlchemy idioms."""
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def _set_search_path(session: AsyncSession, tenant_schema: str | None) -> None:
    """SET LOCAL search_path on the current transaction.

    Per ARCHITECTURE.md § 5: tenant context resolves only from JWT claims,
    never from URL paths or query parameters. This function is the single
    point at which `tenant_schema` ever reaches SQL — `sanitize_tenant_schema`
    must be the only origin of valid schema names.

    For tenant sessions we additionally set two custom GUCs that RLS
    policies read (data_model § 6.6 + § 15.3):

      * `app.current_tenant_id`        — sanitized schema name,
      * `app.tenant_collection_prefix` — the LIKE pattern used by the
                                         pgstac.items RLS policy.

    Both are session-local and scoped to the current transaction. Setting
    them here means every tenant-scoped query inherits them; admin
    sessions (search_path = public) get neither.
    """
    if tenant_schema is None:
        await session.execute(text("SET LOCAL search_path TO public"))
        return

    safe = sanitize_tenant_schema(tenant_schema)
    # Identifiers in PostgreSQL do not bind as params; sanitize then literal.
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
    # set_config(name, value, is_local=true) — equivalent to `SET LOCAL`
    # for custom GUCs, but accepts the value as a bound parameter so we
    # don't have to interpolate strings into SQL ourselves.
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
        {"v": safe},
    )
    await session.execute(
        text("SELECT set_config('app.tenant_collection_prefix', :v, TRUE)"),
        {"v": f"{safe}__%"},
    )


async def _yield_session(tenant_schema: str | None) -> AsyncIterator[AsyncSession]:
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await _set_search_path(session, tenant_schema)
        yield session


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Tenant-scoped session dependency.

    Reads tenant_schema from `request.state.tenant_schema`, set by the
    auth middleware after JWT validation. If absent (anonymous request,
    health probe, admin path), defaults to the `public` schema only —
    this is safe because anonymous requests never reach a route that
    expects tenant data.
    """
    tenant_schema = getattr(request.state, "tenant_schema", None)
    async for session in _yield_session(tenant_schema):
        yield session


async def get_admin_db_session() -> AsyncIterator[AsyncSession]:
    """Admin-only session dependency. search_path = public only.

    Used by platform-admin endpoints that operate on the shared schema
    (e.g., creating new tenants).
    """
    async for session in _yield_session(None):
        yield session
