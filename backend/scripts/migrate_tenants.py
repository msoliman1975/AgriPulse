"""Apply tenant Alembic migrations to every active tenant schema.

Run as:  python -m scripts.migrate_tenants [--only <slug>] [--dry-run]

Checkpointing is per-tenant: each tenant_<id> schema has its own
``alembic_version`` table, so reruns are naturally idempotent — already
up-to-date schemas are no-ops. The script never *creates* schemas; if a
schema is missing the run for that tenant raises and the script
continues with the next one (record of failures printed at the end).

Designed to be safe to re-run — operators reach for this after an
incident, not during normal flow. The tenancy admin endpoint bootstraps
new tenants in-process; this script just keeps existing tenants caught
up after a migration is added.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import create_engine, text

from app.core.settings import get_settings
from app.modules.tenancy.bootstrap import AlembicTenantMigrator

logger = logging.getLogger("migrate_tenants")


@dataclass(frozen=True, slots=True)
class TenantRecord:
    tenant_id: str
    slug: str
    schema_name: str
    status: str


def _list_tenants(only_slug: str | None) -> list[TenantRecord]:
    url = str(get_settings().database_sync_url)
    engine = create_engine(url, future=True)
    try:
        stmt = text(
            """
            SELECT id::text AS tenant_id,
                   slug,
                   schema_name,
                   status
              FROM public.tenants
             WHERE deleted_at IS NULL
               AND status <> 'archived'
               AND (CAST(:only AS text) IS NULL OR slug = CAST(:only AS text))
             ORDER BY created_at
            """
        )
        with engine.begin() as conn:
            rows = conn.execute(stmt, {"only": only_slug}).all()
    finally:
        engine.dispose()
    return [
        TenantRecord(
            tenant_id=row.tenant_id,
            slug=row.slug,
            schema_name=row.schema_name,
            status=row.status,
        )
        for row in rows
    ]


def _migrate_one(tenant: TenantRecord, *, dry_run: bool) -> None:
    if dry_run:
        logger.info("would migrate %s (%s)", tenant.slug, tenant.schema_name)
        return
    AlembicTenantMigrator().bootstrap(tenant.schema_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Migrate just this tenant (by slug).")
    parser.add_argument("--dry-run", action="store_true", help="List actions without executing.")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    )

    tenants = _list_tenants(args.only)
    if not tenants:
        logger.warning("no active tenants found")
        return 0

    failures: list[tuple[TenantRecord, BaseException]] = []
    for tenant in tenants:
        logger.info(
            "migrating tenant slug=%s schema=%s status=%s",
            tenant.slug,
            tenant.schema_name,
            tenant.status,
        )
        try:
            _migrate_one(tenant, dry_run=args.dry_run)
        except Exception as exc:
            logger.error("failed: %s — %s", tenant.slug, exc)
            failures.append((tenant, exc))

    logger.info(
        "done: %d total, %d ok, %d failed",
        len(tenants),
        len(tenants) - len(failures),
        len(failures),
    )
    if failures:
        for tenant, exc in failures:
            logger.error("  - %s (%s): %s", tenant.slug, tenant.schema_name, exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
