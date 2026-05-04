"""Alembic environment for the shared `public` schema.

Connection URL comes from app.core.settings (env-driven). Migrations
target only `public` — tenant schemas are handled by migrations/tenant.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Register every public-schema ORM model with `Base.metadata` so future
# `--autogenerate` runs see them. Hand-written migrations do not need
# this, but it is cheap to keep the registry warm.
import app.modules.farms.models
import app.modules.iam.models
import app.modules.imagery.models
import app.modules.indices.models
import app.modules.tenancy.models
from app.core.settings import get_settings
from app.shared.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    """Alembic uses the sync driver. Settings exposes a parallel DSN."""
    return str(get_settings().database_sync_url)


def run_migrations_offline() -> None:
    """Generate SQL without a DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="public",
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live connection."""
    cfg = config.get_section(config.config_ini_section) or {}
    cfg["sqlalchemy.url"] = _sync_url()

    connectable = engine_from_config(
        cfg,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="public",
            include_schemas=False,
            compare_type=True,
            compare_server_default=True,
            # One transaction per migration. Required by 0007's pgstac
            # bootstrap: pgstac does `CREATE EXTENSION btree_gist`, which
            # blocks on row locks held by any earlier migration whose
            # transaction is still open. With per-migration transactions,
            # each prior migration commits before the next begins, so the
            # bootstrap sees a clean catalog state.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
