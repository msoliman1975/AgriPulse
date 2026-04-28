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

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from app.core.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import Request


# Public name kept for typing in module imports.
Engine = AsyncEngine

_engine: AsyncEngine | None = None
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
    """
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        echo=settings.database_echo,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = create_engine()
        return _engine


async def dispose_engine() -> None:
    """Dispose the process-wide engine. Used in app shutdown and tests."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            await _engine.dispose()
            _engine = None


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
    """
    if tenant_schema is None:
        await session.execute(text("SET LOCAL search_path TO public"))
        return

    safe = sanitize_tenant_schema(tenant_schema)
    # Identifiers in PostgreSQL do not bind as params; sanitize then literal.
    await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))


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
