"""Move this tenant's `now()` column defaults onto `public.app_now()`.

The tenant half of public migration 0089. That one creates
`public.app_now()`, rewrites `public.set_updated_at()` to call it, and
rewrites the defaults in `public` and in the Timescale chunk schema. This
one rewrites the defaults inside one tenant schema. It runs once per
tenant, the way every tenant migration does.

A stored column DEFAULT is resolved when the column is created, so it
keeps calling `pg_catalog.now()` whatever a session later does. Rewriting
it is the only way a demo-history replay can reach it.

Timescale chunks are left alone, here and in public 0089. A chunk
refuses `ALTER TABLE ... SET DEFAULT` outright, and a partition's own
default is ignored when the row arrives through the parent. Both were
measured on the production database inside a rolled-back transaction.
Every write in this application goes through the hypertable.

Behaviour does not change for any tenant. With the `agripulse.now`
setting unset, which is the case on every request and every scheduled
task, `public.app_now()` returns `now()`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0092"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FROM_NOW = "('now()', 'pg_catalog.now()')"
FROM_APP_NOW = "('app_now()', 'public.app_now()')"


def _rewrite_defaults(match_exprs: str, to_expr: str) -> str:
    """Build a DO block that swaps a default expression in this schema.

    `current_schema()` is the tenant schema: the tenant migration runner
    pins `search_path` to it before running any revision.
    """
    return f"""
DO $do$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT c.relname AS table_name,
               a.attname AS column_name
          FROM pg_attrdef d
          JOIN pg_class c ON c.oid = d.adrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a
            ON a.attrelid = d.adrelid AND a.attnum = d.adnum
         WHERE pg_get_expr(d.adbin, d.adrelid) IN {match_exprs}
           AND n.nspname = current_schema()
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ALTER COLUMN %I SET DEFAULT {to_expr}',
            current_schema(), r.table_name, r.column_name
        );
    END LOOP;
END
$do$;
"""


def upgrade() -> None:
    op.execute(_rewrite_defaults(FROM_NOW, "public.app_now()"))


def downgrade() -> None:
    op.execute(_rewrite_defaults(FROM_APP_NOW, "now()"))
