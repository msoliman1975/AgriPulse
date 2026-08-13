"""Orphan scanner — the independent check that a purge actually finished.

Walks the same manifest the purge engine walks, but asks the opposite question:
for every registered ownership column, are there rows pointing at an owner that
no longer exists?

Two uses:

* **Verification.** Every purge re-runs the scanner against the id it just
  deleted and stamps the result on the receipt. A purge that reports orphans is
  a failed purge, and says so, rather than quietly leaving residue.
* **Audit.** Run standalone it reports pre-existing residue — including from the
  tenant purges performed before this module existed, which leaked
  ``public.decision_trees``, ``public.backfill_runs`` and ``public.farm_scopes``
  rows by design of the old three-table cleanup.

``public.farm_scopes`` is the awkward one: it references ``farms.id`` across a
schema boundary, so "does the owner exist?" can only be answered by checking
every tenant schema. That is why it has never been enforced by a FK and why the
existing hourly detector (``farms/consistency_check.py``) only reports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db.session import sanitize_tenant_schema
from app.shared.purge.registry import (
    BLOCK_OWNED,
    FARM_OWNED,
    TENANT_PUBLIC_OWNED,
    OwnedTable,
)

logger = logging.getLogger(__name__)

# owner column -> (parent table, whether the parent lives in public)
_PARENTS: dict[str, tuple[str, bool]] = {
    "block_id": ("blocks", False),
    "farm_id": ("farms", False),
    "tenant_id": ("tenants", True),
}


@dataclass(frozen=True)
class Orphan:
    schema: str
    table: str
    column: str
    rows: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "table": self.table,
            "column": self.column,
            "rows": self.rows,
        }


@dataclass
class ScanResult:
    orphans: list[Orphan]
    scanned_tables: int
    schemas: list[str]

    @property
    def total_orphan_rows(self) -> int:
        return sum(o.rows for o in self.orphans)

    def as_dict(self) -> dict[str, Any]:
        return {
            "orphans": [o.as_dict() for o in self.orphans],
            "orphans_found": len(self.orphans),
            "orphan_rows": self.total_orphan_rows,
            "scanned_tables": self.scanned_tables,
            "schemas": self.schemas,
        }


async def scan_tenant_schema(session: AsyncSession, tenant_schema: str) -> ScanResult:
    """Scan one tenant schema for rows whose block/farm owner is gone."""
    safe = sanitize_tenant_schema(tenant_schema)
    orphans: list[Orphan] = []
    scanned = 0

    for owned in _tenant_scoped(BLOCK_OWNED + FARM_OWNED):
        parent, _ = _PARENTS[str(owned.owner_column)]
        if not await _table_exists(session, safe, owned.table):
            continue
        scanned += 1
        # `safe` is sanitize_tenant_schema output; table/column/parent come only
        # from the hardcoded manifest. Nothing here is user input.
        n = await _count(
            session,
            f"""
            SELECT count(*) FROM "{safe}"."{owned.table}" t
             WHERE t.{owned.owner_column} IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM "{safe}"."{parent}" p WHERE p.id = t.{owned.owner_column}
               )
            """,  # noqa: S608
        )
        if n:
            orphans.append(Orphan(safe, owned.table, str(owned.owner_column), n))

    return ScanResult(orphans=orphans, scanned_tables=scanned, schemas=[safe])


async def scan_public(session: AsyncSession) -> ScanResult:
    """Scan public-schema rows keyed by tenant_id or farm_id.

    ``tenant_id`` resolves against ``public.tenants``. ``farm_id`` cannot resolve
    against anything in ``public`` — the farm lives in a tenant schema — so those
    tables are checked against the union of every live tenant's ``farms``.
    """
    orphans: list[Orphan] = []
    scanned = 0

    schemas = await live_tenant_schemas(session)

    for owned in TENANT_PUBLIC_OWNED + tuple(t for t in FARM_OWNED if t.schema == "public"):
        if owned.owner_column is None:
            continue
        if not await _table_exists(session, "public", owned.table):
            continue
        scanned += 1
        if owned.owner_column == "tenant_id":
            n = await _count(
                session,
                f"""
                SELECT count(*) FROM public.{owned.table} t
                 WHERE t.tenant_id IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM public.tenants p WHERE p.id = t.tenant_id)
                """,  # noqa: S608
            )
        else:
            n = await _count_orphan_farm_refs(session, owned, schemas)
        if n:
            orphans.append(Orphan("public", owned.table, owned.owner_column, n))

    scanned += 1
    unreachable = await _count_unreachable_users(session)
    if unreachable:
        orphans.append(Orphan("public", "users", "tenant_memberships", unreachable))

    return ScanResult(orphans=orphans, scanned_tables=scanned, schemas=["public"])


async def _count_unreachable_users(session: AsyncSession) -> int:
    """Users nobody can reach: no tenant membership and no platform role.

    Not an ownership-column orphan — ``public.users`` has no owner — but the
    same failure in a different shape, and the one a tenant purge used to
    leave behind on every run. Such a row still holds the unique email, so it
    silently blocks re-inviting that person anywhere on the platform.

    Safe as a standalone audit because a user is materialised in the same
    transaction as its membership (see the owner-provisioning path in
    ``tenancy.service``); there is no committed window where a live user has
    neither.
    """
    return await _count(
        session,
        """
        SELECT count(*) FROM public.users u
         WHERE NOT EXISTS (
                 SELECT 1 FROM public.tenant_memberships m WHERE m.user_id = u.id)
           AND NOT EXISTS (
                 SELECT 1 FROM public.platform_role_assignments p WHERE p.user_id = u.id)
        """,
    )


async def scan_all(session: AsyncSession) -> ScanResult:
    """Full sweep: every live tenant schema plus public."""
    result = await scan_public(session)
    for schema in await live_tenant_schemas(session):
        part = await scan_tenant_schema(session, schema)
        result.orphans.extend(part.orphans)
        result.scanned_tables += part.scanned_tables
        result.schemas.extend(part.schemas)
    return result


async def live_tenant_schemas(session: AsyncSession) -> list[str]:
    """Tenant schemas that both exist in ``public.tenants`` and are present.

    A schema present on disk but absent from ``public.tenants`` is itself a
    purge failure; :func:`scan_stray_schemas` reports those separately.
    """
    rows = await session.execute(
        text(
            """
            SELECT t.schema_name
              FROM public.tenants t
              JOIN information_schema.schemata s ON s.schema_name = t.schema_name
             ORDER BY t.schema_name
            """
        )
    )
    out: list[str] = []
    for (name,) in rows:
        try:
            out.append(sanitize_tenant_schema(name))
        except ValueError:
            logger.warning("skipping_suspicious_schema", extra={"schema": name})
    return out


async def scan_stray_schemas(session: AsyncSession) -> list[str]:
    """Tenant schemas on disk with no matching ``public.tenants`` row.

    Left behind when a purge dropped the tenant row but its DROP SCHEMA failed
    (or vice versa) — the residue a half-completed purge leaves.
    """
    rows = await session.execute(
        text(
            """
            SELECT s.schema_name
              FROM information_schema.schemata s
             WHERE s.schema_name LIKE 'tenant\\_%'
               AND NOT EXISTS (
                   SELECT 1 FROM public.tenants t WHERE t.schema_name = s.schema_name
               )
             ORDER BY 1
            """
        )
    )
    return [r[0] for r in rows]


# --- helpers ---------------------------------------------------------------


def _tenant_scoped(group: tuple[OwnedTable, ...]) -> list[OwnedTable]:
    """Manifest entries checkable by a simple owner lookup, de-duplicated.

    Transitively-owned tables (``where_sql``) are skipped: their owner is another
    owned row, so they cannot orphan independently of it.
    """
    seen: set[tuple[str, str]] = set()
    out: list[OwnedTable] = []
    for owned in group:
        if owned.schema != "tenant" or owned.owner_column is None:
            continue
        key = (owned.table, owned.owner_column)
        if key in seen:
            continue
        seen.add(key)
        out.append(owned)
    return out


async def _count_orphan_farm_refs(
    session: AsyncSession, owned: OwnedTable, schemas: list[str]
) -> int:
    """Rows in a public table whose ``farm_id`` exists in no tenant schema."""
    if not schemas:
        # No live tenants: every farm reference is an orphan.
        return await _count(
            session,
            f"SELECT count(*) FROM public.{owned.table} WHERE farm_id IS NOT NULL",  # noqa: S608
        )
    # Schemas are sanitize_tenant_schema output (see live_tenant_schemas).
    union = " UNION ALL ".join(f'SELECT id FROM "{s}".farms' for s in schemas)  # noqa: S608
    return await _count(
        session,
        f"""
        SELECT count(*) FROM public.{owned.table} t
         WHERE t.farm_id IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM ({union}) f WHERE f.id = t.farm_id)
        """,  # noqa: S608
    )


async def _table_exists(session: AsyncSession, schema: str, table: str) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = :s AND table_name = :t AND table_type = 'BASE TABLE'"
                ),
                {"s": schema, "t": table},
            )
        ).scalar_one_or_none()
    )


async def _count(session: AsyncSession, sql: str) -> int:
    return int((await session.execute(text(sql))).scalar_one_or_none() or 0)
