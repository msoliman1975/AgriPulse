"""Tenant schema provisioning: CREATE SCHEMA + run tenant Alembic migrations.

Pulled out of `service.py` so tests can swap a fake migrator and so the
runner script (`scripts/migrate_tenants.py`) can reuse the same code
path on existing tenants.

The implementation here is **synchronous** by design — DDL outside a
managed transaction is the only safe way to ``CREATE SCHEMA`` and run
Alembic, and Alembic's API is sync-only. The async service awaits this
in a thread executor.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Protocol

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.shared.db.session import sanitize_tenant_schema

# Repo-root alembic.ini; `app/__init__.py` lives at backend/app/, so two
# parents up (../..) lands on backend/ where alembic.ini sits.
ALEMBIC_INI = Path(app.__file__).resolve().parent.parent / "alembic.ini"


class TenantSchemaMigrator(Protocol):
    """Bootstrap, upgrade, or drop a single tenant schema."""

    def bootstrap(self, schema_name: str) -> None: ...

    def purge(self, schema_name: str) -> None: ...


class AlembicTenantMigrator:
    """Default migrator: CREATE SCHEMA IF NOT EXISTS + alembic upgrade head."""

    def __init__(self, alembic_ini: Path | None = None) -> None:
        self._alembic_ini = alembic_ini or ALEMBIC_INI
        self._log = get_logger(__name__)

    def bootstrap(self, schema_name: str) -> None:
        safe = sanitize_tenant_schema(schema_name)
        self._create_schema(safe)
        self._run_alembic_upgrade(safe)

    def purge(self, schema_name: str) -> None:
        """DROP SCHEMA …CASCADE. Irreversible — caller is responsible for backup."""
        safe = sanitize_tenant_schema(schema_name)
        url = str(get_settings().database_sync_url)
        engine = create_engine(url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{safe}" CASCADE'))
            self._log.info("tenant_schema_purged", schema=safe)
        finally:
            engine.dispose()

    def _create_schema(self, schema_name: str) -> None:
        url = str(get_settings().database_sync_url)
        engine = create_engine(url, future=True)
        try:
            with engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
            self._log.info("tenant_schema_created", schema=schema_name)
        finally:
            engine.dispose()

    def _run_alembic_upgrade(self, schema_name: str) -> None:
        cfg = Config(str(self._alembic_ini), ini_section="tenant")
        # Pass schema as -x argument so env.py can read it via
        # context.get_x_argument(...). Programmatic Alembic reads
        # cfg.cmd_opts.x for that purpose.
        cfg.cmd_opts = Namespace(x=[f"schema={schema_name}"])
        command.upgrade(cfg, "head")
        self._log.info("tenant_schema_migrated", schema=schema_name)
