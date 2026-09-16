"""One clock the application can move, for demo-history replay.

The demo farm needs activities, decision tree runs, recommendations and
alerts whose timestamps read as months old. The only honest way to produce
them is to run the real engine and make it believe the date is in the past.
Postgres writes a large share of those timestamps itself, so a Python-side
clock alone cannot do it.

This migration adds `public.app_now()`:

    COALESCE(current_setting('agripulse.now', true)::timestamptz, now())

With the setting unset or empty it returns `now()`, so behaviour is
unchanged for every tenant. A replay sets `agripulse.now` on its own
transactions and every timestamp written under it lands on the simulated
day.

Three places then move onto it.

1. `public.set_updated_at()`, the BEFORE UPDATE trigger every audited table
   attaches. Its body said `NEW.updated_at := now()`, which overwrote any
   value the caller supplied.
2. Every column default that is exactly `now()`. There are 66 in `public`.
   A stored DEFAULT is resolved to `pg_catalog.now()` when the column is
   created, so it cannot be redirected at run time by any session setting.
   Rewriting the default is the only way to reach it. The loop reads the
   catalog rather than naming tables, so a table added since this was
   written is covered too.
Timescale chunks are deliberately left alone. Two measurements on the
production database, inside a rolled-back transaction, decided that:

* `ALTER TABLE <chunk> ALTER COLUMN ... SET DEFAULT` is refused outright
  with `operation not supported on chunk tables` (TimescaleDB 2.26.4).
* A partition's own default is ignored when the row arrives through the
  parent. Inserting into the parent used the parent's default; only a
  direct insert into the partition used the partition's. Every write in
  this application goes through the hypertable, so the chunk defaults are
  never the ones that fire.

The `search_path` alternative was measured and rejected. Shadowing `now()`
with a function in a schema placed ahead of `pg_catalog` does redirect raw
SQL and plpgsql bodies, including the existing trigger. It does not reach a
stored column default, and 46 places in the application set `search_path`
themselves, so any of them would drop the shim and the timestamps would
quietly become real again.

`app_now()` is STABLE, not IMMUTABLE: it returns one value for the whole
statement, like `now()`, and must never be folded into an index or a
constraint.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0089"
down_revision: str | None = "0088"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_NOW_FN = """
CREATE OR REPLACE FUNCTION public.app_now()
RETURNS timestamptz
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT COALESCE(
        NULLIF(current_setting('agripulse.now', true), '')::timestamptz,
        pg_catalog.now()
    )
$$;
"""

APP_NOW_COMMENT = """
COMMENT ON FUNCTION public.app_now() IS
  'Current time, or the instant named by the agripulse.now setting. '
  'Application SQL calls this instead of now() so a demo-history replay '
  'can write past timestamps. Unset means now().';
"""

# Only the assignment changes. A caller that sets updated_at itself still
# has it overwritten, exactly as before, so no write path changes meaning.
TOUCH_FN_NEW = """
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := public.app_now();
    RETURN NEW;
END;
$$;
"""

TOUCH_FN_OLD = """
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
"""


# `pg_get_expr` prints the expression as the current search_path would
# write it, so the same default reads as `now()` or `pg_catalog.now()`
# depending on the session. Both spellings are matched on the way in, and
# both spellings of the new one on the way out.
FROM_NOW = "('now()', 'pg_catalog.now()')"
FROM_APP_NOW = "('app_now()', 'public.app_now()')"


# The upgrade rewrites `public` only. Each tenant schema is rewritten by
# the matching tenant migration, which runs once per tenant.
UPGRADE_SCOPE = "n.nspname = 'public'"

# The downgrade has to reach further. A column default that calls
# `public.app_now()` is a recorded dependency on that function, so
# `DROP FUNCTION` is refused while any of them survives — including the
# ones in tenant schemas, which the public chain cannot downgrade. Measured
# on the production database: "cannot drop function ... because other
# objects depend on it ... default value for column".
#
# System schemas are excluded, and so is `_timescaledb_internal`: the
# upgrade never wrote into a chunk, so there is nothing there to undo.
DOWNGRADE_SCOPE = (
    r"n.nspname NOT LIKE 'pg\_%' "
    r"AND n.nspname NOT LIKE '\_timescaledb%' "
    r"AND n.nspname <> 'information_schema'"
)


def _rewrite_defaults(match_exprs: str, to_expr: str, scope: str) -> str:
    """Build a DO block that swaps one default expression for another.

    `scope` is a predicate on `n.nspname` that decides which schemas the
    block walks. `_timescaledb_internal` is never in scope: its chunks
    refuse the ALTER outright, and a chunk default never fires for a write
    that arrives through the hypertable.

    A column already carrying the target expression does not match, so the
    block is safe to run more than once.
    """
    return f"""
DO $do$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT n.nspname AS schema_name,
               c.relname AS table_name,
               a.attname AS column_name
          FROM pg_attrdef d
          JOIN pg_class c ON c.oid = d.adrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a
            ON a.attrelid = d.adrelid AND a.attnum = d.adnum
         WHERE pg_get_expr(d.adbin, d.adrelid) IN {match_exprs}
           AND {scope}
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ALTER COLUMN %I SET DEFAULT {to_expr}',
            r.schema_name, r.table_name, r.column_name
        );
    END LOOP;
END
$do$;
"""


def upgrade() -> None:
    op.execute(APP_NOW_FN)
    op.execute(APP_NOW_COMMENT)
    op.execute(TOUCH_FN_NEW)
    op.execute(_rewrite_defaults(FROM_NOW, "public.app_now()", UPGRADE_SCOPE))


def downgrade() -> None:
    op.execute(_rewrite_defaults(FROM_APP_NOW, "now()", DOWNGRADE_SCOPE))
    op.execute(TOUCH_FN_OLD)
    op.execute("DROP FUNCTION IF EXISTS public.app_now()")
