"""The guard: every ownership column must be registered or explicitly exempt.

This is the test that makes purge's completeness a property of the codebase
rather than a claim in a docstring. It introspects a freshly-migrated tenant
schema and the public schema for every column named ``tenant_id``, ``farm_id``
or ``block_id``, and fails when it finds one the purge manifest does not cover.

A migration that adds an ownership column now has exactly two options: register
the table in ``app.shared.purge.registry``, or add it to ``EXEMPT_PAIRS`` with a
reason. Silently introducing a new orphan source stops being possible.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.purge.registry import (
    EXEMPT_PAIRS,
    OWNERSHIP_COLUMNS,
    all_owned,
    registered_pairs,
)

pytestmark = [pytest.mark.integration]


async def _ownership_columns(session: AsyncSession, schema: str) -> list[tuple[str, str, str]]:
    """(table, column, table_type) for every ownership column in a schema."""
    rows = await session.execute(
        text(
            """
            SELECT c.table_name, c.column_name, t.table_type
              FROM information_schema.columns c
              JOIN information_schema.tables t
                ON t.table_schema = c.table_schema AND t.table_name = c.table_name
             WHERE c.table_schema = :schema
               AND c.column_name = ANY(:cols)
             ORDER BY 1, 2
            """
        ),
        {"schema": schema, "cols": list(OWNERSHIP_COLUMNS)},
    )
    return [(r[0], r[1], r[2]) for r in rows]


def _unregistered(found: list[tuple[str, str, str]]) -> list[str]:
    registered = registered_pairs()
    # Tables reached transitively (grid_cells via grid_configs) are covered by
    # table name alone — they have no owner column of their own to register.
    via_tables = {t.table for t in all_owned() if t.where_sql is not None}
    missing = []
    for table, column, _type in found:
        if (table, column) in registered:
            continue
        if (table, column) in EXEMPT_PAIRS:
            continue
        if table in via_tables:
            continue
        missing.append(f"{table}.{column}")
    return missing


@pytest.mark.asyncio
async def test_tenant_schema_has_no_unowned_columns(admin_session: AsyncSession) -> None:
    slug = f"reg-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")

    found = await _ownership_columns(admin_session, tenant.schema_name)
    assert found, "expected the tenant schema to have ownership columns at all"

    missing = _unregistered(found)
    assert not missing, (
        "These tenant-schema columns express ownership but the purge manifest "
        "does not cover them, so a purge would orphan their rows:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd them to app/shared/purge/registry.py (BLOCK_OWNED or "
        "FARM_OWNED), or to EXEMPT_PAIRS with a reason."
    )


@pytest.mark.asyncio
async def test_public_schema_has_no_unowned_columns(admin_session: AsyncSession) -> None:
    found = await _ownership_columns(admin_session, "public")
    missing = _unregistered(found)
    assert not missing, (
        "These public-schema columns reference a tenant or farm but the purge "
        "manifest does not cover them, so they survive a purge forever:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd them to TENANT_PUBLIC_OWNED / FARM_OWNED in "
        "app/shared/purge/registry.py, or to EXEMPT_PAIRS with a reason."
    )


@pytest.mark.asyncio
async def test_manifest_tables_all_exist(admin_session: AsyncSession) -> None:
    """The manifest must not name a table that no longer exists.

    A stale entry is quieter than a missing one but just as wrong: the engine
    would raise mid-purge, after some tables had already been emptied.
    """
    slug = f"reg-{uuid4().hex[:8]}"
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")

    stale: list[str] = []
    for owned in all_owned():
        schema = "public" if owned.schema == "public" else tenant.schema_name
        exists = (
            await admin_session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": schema, "t": owned.table},
            )
        ).scalar_one_or_none()
        if not exists:
            stale.append(f"{schema}.{owned.table}")
    assert not stale, f"purge manifest names tables that do not exist: {stale}"
