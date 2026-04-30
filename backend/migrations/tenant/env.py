"""Alembic environment for per-tenant schemas.

Run as:  alembic -n tenant -x schema=tenant_<uuid> upgrade head

The ``-x schema=...`` argument is required and must match a real
``tenant_<uuid>`` schema name. ``scripts/migrate_tenants.py`` loops the
``public.tenants`` table and invokes this env once per active tenant.

Each migration runs with ``search_path = <schema>, public`` and writes
its bookkeeping to a per-tenant ``alembic_version`` table inside the
schema, so every tenant tracks its own revision independently.
"""

from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Register every tenant-schema ORM model with `Base.metadata` so future
# `--autogenerate` runs see them.
import app.modules.audit.models
import app.modules.farms.models
from app.core.settings import get_settings
from app.shared.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_SCHEMA_RE = re.compile(r"^tenant_[a-z0-9_]{1,64}$")


def _resolve_schema() -> str:
    """Read ``-x schema=...`` from the Alembic CLI; refuse anything else."""
    x_args = context.get_x_argument(as_dictionary=True)
    schema = x_args.get("schema")
    if not schema:
        raise RuntimeError("tenant migrations require -x schema=tenant_<uuid> on the CLI")
    if not _SCHEMA_RE.fullmatch(schema):
        raise RuntimeError(f"Invalid tenant schema name: {schema!r}")
    return schema


def _sync_url() -> str:
    return str(get_settings().database_sync_url)


def run_migrations_offline() -> None:
    schema = _resolve_schema()
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version",
        version_table_schema=schema,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    schema = _resolve_schema()

    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _sync_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        # Pin search_path for the duration of this migration run. The schema
        # itself is created by the tenancy bootstrap, *not* by Alembic — so
        # the schema must already exist when this env runs.
        connection.execute(text(f"SET search_path TO {schema}, public"))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table="alembic_version",
            version_table_schema=schema,
            include_schemas=False,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
