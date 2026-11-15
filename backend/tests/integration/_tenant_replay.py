"""Replay tenant migrations as one recorded script instead of running Alembic.

Almost every integration test creates its own tenant, and each tenant used to
run all ~100 tenant Alembic migrations: about 750 statements, ~1.1 s on the
TimescaleDB image, most of the suite's runtime. Replaying the same statements
as one script, in one round trip and one transaction, takes ~0.45 s.

How it stays faithful:

* The script is not written by hand. At session start one template tenant is
  migrated by the real ``AlembicTenantMigrator`` while every statement it sends
  is recorded, so the script is exactly what Alembic did against an empty
  schema with this session's migrations. A new migration is picked up with no
  extra step.
* A fresh tenant schema holds no data apart from ``alembic_version``, so there
  is no seeded row whose recorded value could go stale. ``install`` checks
  that, and refuses the shortcut if a migration ever starts seeding rows.
* The first replayed tenant is compared with the template (columns, indexes,
  constraints, views, functions, triggers, hypertables, continuous aggregates,
  jobs and ``alembic_version``) and the session fails loudly on any difference.
* Production is untouched. ``create_tenant`` there still runs Alembic; only the
  test session swaps the migrator's ``bootstrap``.

``AGRIPULSE_TEST_REAL_TENANT_MIGRATIONS=1`` turns the shortcut off.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, event, pool
from sqlalchemy.engine import Engine

OPT_OUT_ENV = "AGRIPULSE_TEST_REAL_TENANT_MIGRATIONS"

# TimescaleDB numbers its internal tables globally, so two otherwise identical
# tenants differ in `_materialized_hypertable_<n>` and `cagg_watermark(<n>)`.
_TSDB_IDS = re.compile(r"(_materialized_hypertable_|cagg_watermark\()\d+")


def _shape(conn: Any, schema: str) -> dict[str, list[tuple[Any, ...]]]:
    """Everything about a schema that a migration can create, schema-name neutral."""

    def q(sql: str, *args: Any) -> list[tuple[Any, ...]]:
        rows = conn.execute(sql, args).fetchall()
        return sorted(
            tuple(_TSDB_IDS.sub(r"\1N", v) if isinstance(v, str) else v for v in row)
            for row in rows
        )

    s = schema
    return {
        "columns": q(
            "SELECT table_name, column_name, data_type, "
            "       coalesce(replace(column_default, %s, 'S'), ''), is_nullable "
            "  FROM information_schema.columns WHERE table_schema = %s",
            s,
            s,
        ),
        "indexes": q(
            "SELECT indexname, replace(indexdef, %s, 'S') FROM pg_indexes WHERE schemaname = %s",
            s,
            s,
        ),
        "constraints": q(
            "SELECT conname, replace(pg_get_constraintdef(c.oid), %s, 'S') "
            "  FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
            " WHERE nspname = %s",
            s,
            s,
        ),
        "views": q(
            "SELECT viewname, replace(definition, %s, 'S') FROM pg_views WHERE schemaname = %s",
            s,
            s,
        ),
        "functions": q(
            "SELECT p.proname, replace(pg_get_functiondef(p.oid), %s, 'S') "
            "  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE nspname = %s AND p.prokind = 'f'",
            s,
            s,
        ),
        "triggers": q(
            "SELECT tgname, replace(pg_get_triggerdef(t.oid), %s, 'S') "
            "  FROM pg_trigger t JOIN pg_class r ON r.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = r.relnamespace "
            " WHERE nspname = %s AND NOT tgisinternal",
            s,
            s,
        ),
        "hypertables": q(
            "SELECT hypertable_name, num_dimensions, compression_enabled "
            "  FROM timescaledb_information.hypertables WHERE hypertable_schema = %s",
            s,
        ),
        "caggs": q(
            "SELECT view_name, materialized_only "
            "  FROM timescaledb_information.continuous_aggregates WHERE view_schema = %s",
            s,
        ),
        "jobs": q(
            "SELECT proc_name, hypertable_name, schedule_interval::text "
            "  FROM timescaledb_information.jobs WHERE hypertable_schema = %s",
            s,
        ),
        "alembic_version": q(f'SELECT version_num FROM "{s}".alembic_version'),
    }


def _nonempty_tables(conn: Any, schema: str) -> dict[str, int]:
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = %s", (schema,)
        ).fetchall()
    ]
    counts = {
        t: conn.execute(f'SELECT count(*) FROM "{schema}"."{t}"').fetchone()[0] for t in tables
    }
    return {t: n for t, n in counts.items() if n and t != "alembic_version"}


class ReplayedTenantBootstrap:
    """Records one real tenant migration, then replays it for every new tenant."""

    def __init__(self, sync_url: str) -> None:
        self._engine = create_engine(sync_url, future=True, poolclass=pool.NullPool)
        self._template = ""
        self._script = ""
        self._verified = False
        self._lock = threading.Lock()

    def _raw(self) -> Any:
        """A pool proxy over a raw psycopg connection.

        Raw because the script holds literal `%` and must not pass through a
        driver paramstyle. Callers use ``.driver_connection`` and close the
        proxy, never the psycopg connection itself.
        """
        return self._engine.raw_connection()

    def record(self, real_bootstrap: Any) -> None:
        from psycopg import ClientCursor

        captured: list[tuple[str, Any]] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
            captured.append((statement, parameters))

        self._template = f"tenant_{uuid4().hex}"
        event.listen(Engine, "before_cursor_execute", _capture)
        try:
            real_bootstrap(self._template)
        finally:
            event.remove(Engine, "before_cursor_execute", _capture)

        proxy = self._raw()
        raw = proxy.driver_connection
        try:
            leftover = _nonempty_tables(raw.cursor(), self._template)
            if leftover:
                raise RuntimeError(
                    "a tenant migration now seeds rows into a fresh schema "
                    f"({leftover}); replaying recorded values would copy them verbatim. "
                    f"Teach tests/integration/_tenant_replay.py about it or set {OPT_OUT_ENV}=1."
                )
            with ClientCursor(raw) as cc:
                self._script = ";\n".join(
                    cc.mogrify(statement, parameters or {}) for statement, parameters in captured
                )
        finally:
            proxy.close()

    def bootstrap(self, schema_name: str) -> None:
        from app.shared.db.session import sanitize_tenant_schema

        safe = sanitize_tenant_schema(schema_name)
        proxy = self._raw()
        raw = proxy.driver_connection
        try:
            raw.execute(self._script.replace(self._template, safe).encode(), prepare=False)
            raw.commit()
            with self._lock:
                if not self._verified:
                    self._verify(raw, safe)
                    self._verified = True
        finally:
            proxy.close()

    def _verify(self, raw: Any, schema: str) -> None:
        cur = raw.cursor()
        # The script ends on `SET search_path TO <schema>, public`. Postgres
        # prints references into a schema on the path unqualified, so without
        # this reset one side would read `S.blocks` and the other `blocks`.
        cur.execute("RESET search_path")
        want, got = _shape(cur, self._template), _shape(cur, schema)
        diff = [k for k in want if want[k] != got[k]]
        if diff:
            detail = {
                k: {
                    "only_in_template": sorted(set(want[k]) - set(got[k]))[:3],
                    "only_in_replay": sorted(set(got[k]) - set(want[k]))[:3],
                }
                for k in diff
            }
            raise RuntimeError(
                f"replayed tenant schema differs from the Alembic-migrated template in {diff}: "
                f"{detail}. Set {OPT_OUT_ENV}=1 to run real migrations while this is investigated."
            )

    def dispose(self) -> None:
        self._engine.dispose()


def enabled() -> bool:
    return os.environ.get(OPT_OUT_ENV, "") not in {"1", "true", "yes"}
