"""pgstac bootstrap + imagery/indices catalog tables.

Per data_model § 6.2 / § 6.3 / § 7.2 and the Q1 decision in PR-A: pgstac
is bootstrapped as plain SQL via pypgstac (no server-side extension
binary required). The catalogs themselves live in `public` and are
curated by platform admins.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _bootstrap_pgstac() -> None:
    """Run pypgstac's bundled SQL migrations against the current bind.

    pgstac normally ships as a Postgres extension that requires the
    operator to install a shared library on the server. The pypgstac
    Python package re-distributes the same DDL as a sequence of SQL
    files that anyone with a Postgres connection can apply — that's
    what we use, both because our managed Postgres image doesn't
    package pgstac and because it keeps the schema versioned alongside
    the rest of our app code.

    Why we shell out instead of calling `pypgstac.Migrate` in-process:
    pgstac's bootstrap SQL calls `CREATE EXTENSION btree_gist`, which
    takes an `AccessExclusiveLock` on `pg_extension` / `pg_class`.
    Alembic's outer transaction has already written rows to `pg_class`
    (every prior migration's CREATE TABLE), and it's `idle in
    transaction` while a single migration body runs — so an in-process
    pypgstac call inside the alembic transaction blocks indefinitely
    on transaction `xid` 750+. A subprocess launches a fully
    independent backend that can take the catalog locks without
    contending with the parent transaction. (Diagnosed via
    `pg_stat_activity` + `pg_locks` while the tests hung.)

    The subprocess inherits `PYTHONUTF8=1` so pypgstac's bundled SQL
    files (which contain non-ASCII bytes) are decoded as UTF-8 even
    on Windows where the default codec is cp1252.

    pypgstac.Migrate is idempotent — re-running is a no-op once the
    schema is at head, which is what enables `alembic upgrade head`
    to be safe across pre-existing tenants.
    """
    import os
    import subprocess
    import sys

    bind = op.get_bind()
    url = bind.engine.url
    # Strip the `+psycopg` driver suffix; pypgstac's CLI accepts the
    # plain libpq DSN.
    plain_dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    # pypgstac reads `PGDATABASE` and friends from libpq env vars when
    # `--dsn` is not enough; pass the DSN explicitly to keep this hermetic.
    # `pypgstac` does not ship a `__main__.py`; invoke its module entry
    # point directly. `migrate` upgrades to the installed pypgstac
    # version and is idempotent.
    result = subprocess.run(
        [sys.executable, "-m", "pypgstac.pypgstac", "migrate", "--dsn", plain_dsn],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pgstac bootstrap failed.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def upgrade() -> None:
    # ---- pgstac schema --------------------------------------------------
    _bootstrap_pgstac()

    # ---- public.imagery_providers --------------------------------------
    op.create_table(
        "imagery_providers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "config_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_imagery_providers_code"),
        sa.CheckConstraint(
            "kind IN ('commercial_api','open_self_managed','premium_imagery')",
            name="ck_imagery_providers_kind",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_imagery_providers_updated_at "
        "BEFORE UPDATE ON public.imagery_providers "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.imagery_products ---------------------------------------
    op.create_table(
        "imagery_products",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("resolution_m", sa.Numeric(5, 2), nullable=False),
        sa.Column("revisit_days_avg", sa.Numeric(4, 2), nullable=False),
        sa.Column(
            "bands",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "supported_indices",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column("cost_tier", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["public.imagery_providers.id"],
            name="fk_imagery_products_provider_id_imagery_providers",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "provider_id", "code", name="uq_imagery_products_provider_id_code"
        ),
        sa.CheckConstraint(
            "cost_tier IN ('free','low','medium','high','premium')",
            name="ck_imagery_products_cost_tier",
        ),
        sa.CheckConstraint(
            "resolution_m > 0",
            name="ck_imagery_products_resolution_positive",
        ),
        sa.CheckConstraint(
            "revisit_days_avg > 0",
            name="ck_imagery_products_revisit_positive",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_imagery_products_updated_at "
        "BEFORE UPDATE ON public.imagery_products "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.indices_catalog ----------------------------------------
    op.create_table(
        "indices_catalog",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("formula_text", sa.Text(), nullable=False),
        sa.Column("value_min", sa.Numeric(6, 3), nullable=False),
        sa.Column("value_max", sa.Numeric(6, 3), nullable=False),
        sa.Column("physical_meaning", sa.Text(), nullable=True),
        sa.Column(
            "is_standard",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_indices_catalog_code"),
        sa.CheckConstraint(
            "value_max > value_min",
            name="ck_indices_catalog_value_range",
        ),
    )
    op.execute(
        "CREATE TRIGGER trg_indices_catalog_updated_at "
        "BEFORE UPDATE ON public.indices_catalog "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    # Catalog tables drop in reverse FK order.
    op.execute("DROP TRIGGER IF EXISTS trg_indices_catalog_updated_at ON public.indices_catalog")
    op.drop_table("indices_catalog")

    op.execute("DROP TRIGGER IF EXISTS trg_imagery_products_updated_at ON public.imagery_products")
    op.drop_table("imagery_products")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_imagery_providers_updated_at ON public.imagery_providers"
    )
    op.drop_table("imagery_providers")

    # pgstac is intentionally NOT torn down on rollback. Dropping the
    # schema would cascade into pgstac.items, which carries tenant data
    # we never want destroyed by an Alembic downgrade. Operators remove
    # it manually via `pypgstac drop` if a true tear-down is required.
