"""Rebuild an over-partitioned aggregate hypertable onto its current chunking.

Migration 0057 changed `chunk_time_interval` 7d -> 30d and the `block_id`
space partition 4 -> 1 on `block_index_aggregates` / `block_grid_aggregates`
— but **for new chunks only**. It said so, and said why:

    Consolidating them would mean rewriting ~500 compressed chunks, which
    is a maintenance operation to run deliberately against a specific
    tenant, not something to do inside a migration that runs unattended
    against every tenant schema.

This is that operation. It is deliberately NOT a migration.

## Why it is worth running

Everything pre-0057 is still 7 days x 4 space partitions, so on prod
`block_index_aggregates` holds **62,078 rows in 495 chunks (~125/chunk)**.
TimescaleDB plans every chunk it cannot exclude, and chunk exclusion needs
a plan-time-constant time predicate — which the farm scene strip has no
honest way to supply (see `_FARM_SCENE_DAYS_SQL`). So the cost lands in
PLANNING, and grows with history no matter how little data it contains.

Measured on prod 2026-08-17, the scene-strip query against the live table
vs. a rebuilt copy of the same rows:

    metric              495 chunks    32 chunks
    query wall time     404-440 ms    13-15 ms
    Planning Time       378.3 ms      8.9 ms
    Execution Time      29.4 ms       3.3 ms
    plan size           4,088 lines   275 lines
    chunk scan nodes    1,446         96
    on-disk size        148 MB        39 MB

Note the last row: 495 tiny chunks cost ~3.8x the disk of 32 right-sized
ones, so this reclaims space rather than trading space for speed.

## Why a space dimension has to go, and why merge_chunks cannot do it

TimescaleDB 2.26 ships `merge_chunks()`, which looks like the obvious
in-place tool. It refuses:

    ERROR: cannot merge chunk in multi-dimensional hypertable

`block_index_aggregates` has a `block_id` space dimension, and there is no
API to drop a dimension from an existing hypertable. Rebuilding the table
is therefore the only route, and the rebuild drops the space dimension for
good — it never bought anything on a single-node, single-tablespace
deployment, which is exactly what 0057 said when it set partitions to 1.

## What it does to continuous aggregates

A continuous aggregate binds to the hypertable by internal id, not by
name. Renaming a new table into place would leave the CAGGs silently
attached to the OLD table — still readable, never updated again. So they
are dropped and recreated from their own catalog definitions, then fully
refreshed. **`block_index_aggregates` carries two** (`block_index_daily`,
`block_index_weekly`); `block_grid_aggregates` carries none.

That is the one window this script cannot make atomic: `CREATE
MATERIALIZED VIEW ... WITH (timescaledb.continuous)` and
`refresh_continuous_aggregate()` both refuse to run inside a transaction
block. Between the swap commit and the refresh, **reads of those two
aggregates will fail**. It measured ~1.3 s for both on prod's data. The
swap itself IS atomic, and the old table is kept (renamed) until you pass
`--drop-old`, so the rollback is a rename.

Run as::

    # look, touch nothing — prints current shape and the projected one
    python -m scripts.rechunk_aggregate_hypertable --schema tenant_xxx --dry-run

    # rebuild, keeping the old table alongside as <table>__rechunk_old
    python -m scripts.rechunk_aggregate_hypertable --schema tenant_xxx --yes

    # ...and once you are satisfied
    python -m scripts.rechunk_aggregate_hypertable --schema tenant_xxx \
        --drop-old-only

Fidelity is verified before the old table is reachable for dropping: row
counts and a content fingerprint for the table and for every CAGG, taken
before the swap and re-checked after. A mismatch aborts loudly and leaves
`<table>__rechunk_old` in place.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.core.settings import get_settings

logger = logging.getLogger("rechunk_aggregate_hypertable")

# Both tables 0057 re-sized. Only these two are in scope: they are the ones
# that accumulated pre-0057 chunks.
_SUPPORTED = ("block_index_aggregates", "block_grid_aggregates")

# Matches what 0057 set as the going-forward dimension, so a rebuilt table
# and a freshly-created one land on identical chunking.
_CHUNK_INTERVAL = "30 days"

_NEW_SUFFIX = "__rechunk_new"
_OLD_SUFFIX = "__rechunk_old"


@dataclass(frozen=True, slots=True)
class CaggSpec:
    """A continuous aggregate, as much of it as we must put back."""

    name: str
    definition: str
    materialized_only: bool
    compression_enabled: bool
    # (start_offset, end_offset, schedule_interval) of its refresh policy,
    # or None when it has no policy job.
    refresh: tuple[str | None, str | None, str] | None


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """Cheap content identity: a row count plus an order-independent sum.

    `sum(hashtext(...))` is not a cryptographic digest, but it is stable,
    order-independent, and catches the failure this script actually risks —
    rows dropped, duplicated, or silently re-typed by the copy.
    """

    rows: int
    digest: int | None


@dataclass(slots=True)
class Preflight:
    schema: str
    table: str
    rows: int
    chunks: int
    size_pretty: str
    segmentby: str | None
    compress_after: str | None
    caggs: list[CaggSpec] = field(default_factory=list)
    table_fp: Fingerprint | None = None
    cagg_fps: dict[str, Fingerprint] = field(default_factory=dict)


def _q(ident: str) -> str:
    """Quote an identifier for interpolation into DDL.

    Schema and table names come from `public.tenants` and a fixed
    allow-list, never from a request, but this is DDL string-building so it
    quotes anyway.
    """
    return '"' + ident.replace('"', '""') + '"'


def _fingerprint(conn: Connection, schema: str, relation: str) -> Fingerprint:
    # An identifier cannot be a bind parameter, so these interpolate. Both
    # names are `_q()`-quoted, `schema` is checked against `public.tenants`
    # by `_require_known_schema`, and `table` comes from argparse `choices`.
    rows = conn.execute(
        text(f"SELECT count(*) FROM {_q(schema)}.{_q(relation)}")  # noqa: S608
    ).scalar_one()
    digest = conn.execute(
        text(
            f"SELECT sum(hashtext(t::text))::bigint FROM {_q(schema)}.{_q(relation)} t"  # noqa: S608
        )
    ).scalar_one()
    return Fingerprint(rows=int(rows), digest=None if digest is None else int(digest))


def _read_caggs(conn: Connection, schema: str, table: str) -> list[CaggSpec]:
    """Every continuous aggregate whose SOURCE hypertable is `table`.

    Resolved through `_timescaledb_catalog.continuous_agg.raw_hypertable_id`,
    not by looking for the table's name in the view definition.
    `timescaledb_information.continuous_aggregates` names the *view*, so the
    source has to come from somewhere — and the obvious somewhere, the
    rendered definition text, is a trap: `pg_get_viewdef` omits the schema
    for anything already on `search_path`, and `_preflight` puts the tenant
    schema there before this runs. Matching `"<schema>.<table>"` therefore
    found NOTHING on a real tenant, and the failure is silent and bad — the
    caggs would not be dropped, would stay bound to the OLD hypertable
    through the rename, and would go on serving stale numbers forever
    without erroring once.
    """
    rows = conn.execute(
        text(
            """
            SELECT ca.user_view_name AS view_name,
                   i.view_definition,
                   i.materialized_only,
                   i.compression_enabled
              FROM _timescaledb_catalog.continuous_agg ca
              JOIN _timescaledb_catalog.hypertable src
                ON src.id = ca.raw_hypertable_id
              JOIN timescaledb_information.continuous_aggregates i
                ON i.view_schema = ca.user_view_schema
               AND i.view_name = ca.user_view_name
             WHERE src.schema_name = :schema
               AND src.table_name = :table
             ORDER BY ca.user_view_name
            """
        ),
        {"schema": schema, "table": table},
    ).all()

    specs: list[CaggSpec] = []
    for r in rows:
        definition = (r.view_definition or "").strip().rstrip(";")
        if not definition:
            raise SystemExit(f"cannot read definition of cagg {schema}.{r.view_name}")
        policy = conn.execute(
            text(
                """
                SELECT config ->> 'start_offset' AS start_offset,
                       config ->> 'end_offset'   AS end_offset,
                       schedule_interval::text   AS schedule_interval
                  FROM timescaledb_information.jobs
                 WHERE proc_name = 'policy_refresh_continuous_aggregate'
                   AND hypertable_schema = :schema
                   AND config ->> 'mat_hypertable_id' = (
                       SELECT mat_hypertable_id::text
                         FROM _timescaledb_catalog.continuous_agg ca
                         JOIN _timescaledb_catalog.hypertable h
                           ON h.id = ca.mat_hypertable_id
                        WHERE ca.user_view_schema = :schema
                          AND ca.user_view_name = :view
                   )
                """
            ),
            {"schema": schema, "view": r.view_name},
        ).first()
        specs.append(
            CaggSpec(
                name=r.view_name,
                definition=definition,
                materialized_only=bool(r.materialized_only),
                compression_enabled=bool(r.compression_enabled),
                refresh=(
                    (policy.start_offset, policy.end_offset, policy.schedule_interval)
                    if policy
                    else None
                ),
            )
        )
    return specs


def _require_known_schema(conn: Connection, schema: str) -> None:
    """Refuse a schema that does not exist; warn on one that is not a tenant.

    Everything below builds DDL by interpolating this name. It is quoted,
    so the check that matters here is against a typo'd `--schema` — which
    would otherwise surface as a confusing "relation does not exist"
    halfway through, after the new table had already been created.

    Not a hard tenant allow-list, because rehearsing this against a
    scratch copy of a tenant's table is exactly how it should be trialled
    before it is pointed at the real one. A non-tenant schema is legal and
    says so loudly.
    """
    exists = conn.execute(
        text("SELECT 1 FROM pg_namespace WHERE nspname = :schema"),
        {"schema": schema},
    ).scalar_one_or_none()
    if exists is None:
        raise SystemExit(f"schema {schema!r} does not exist")
    tenant = conn.execute(
        text(
            """
            SELECT 1 FROM public.tenants
             WHERE schema_name = :schema AND deleted_at IS NULL
            """
        ),
        {"schema": schema},
    ).scalar_one_or_none()
    if tenant is None:
        logger.warning("%s is not a live tenant schema — assuming this is a rehearsal", schema)


def _preflight(conn: Connection, schema: str, table: str) -> Preflight:
    _require_known_schema(conn, schema)
    conn.execute(text(f"SET search_path TO {_q(schema)}, public"))

    exists = conn.execute(
        text("SELECT to_regclass(:qualified)"), {"qualified": f"{schema}.{table}"}
    ).scalar_one_or_none()
    if exists is None:
        raise SystemExit(f"{schema}.{table} does not exist")

    chunks = conn.execute(
        text(
            """
            SELECT count(*) FROM timescaledb_information.chunks
             WHERE hypertable_schema = :schema AND hypertable_name = :table
            """
        ),
        {"schema": schema, "table": table},
    ).scalar_one()
    size = conn.execute(
        text("SELECT pg_size_pretty(hypertable_size(CAST(:qualified AS regclass)))"),
        {"qualified": f"{schema}.{table}"},
    ).scalar_one()
    segmentby = conn.execute(
        text(
            """
            SELECT string_agg(attname, ',' ORDER BY segmentby_column_index)
              FROM timescaledb_information.compression_settings
             WHERE hypertable_schema = :schema AND hypertable_name = :table
               AND segmentby_column_index IS NOT NULL
            """
        ),
        {"schema": schema, "table": table},
    ).scalar_one_or_none()
    compress_after = conn.execute(
        text(
            """
            SELECT config ->> 'compress_after'
              FROM timescaledb_information.jobs
             WHERE proc_name = 'policy_compression'
               AND hypertable_schema = :schema AND hypertable_name = :table
             LIMIT 1
            """
        ),
        {"schema": schema, "table": table},
    ).scalar_one_or_none()

    pf = Preflight(
        schema=schema,
        table=table,
        rows=0,
        chunks=int(chunks),
        size_pretty=str(size),
        segmentby=segmentby,
        compress_after=compress_after,
    )
    pf.caggs = _read_caggs(conn, schema, table)
    pf.table_fp = _fingerprint(conn, schema, table)
    pf.rows = pf.table_fp.rows
    for c in pf.caggs:
        pf.cagg_fps[c.name] = _fingerprint(conn, schema, c.name)
    return pf


def _describe(pf: Preflight) -> None:
    logger.info("%s.%s", pf.schema, pf.table)
    logger.info("  rows          : %s", f"{pf.rows:,}")
    logger.info("  chunks        : %s", pf.chunks)
    logger.info("  size          : %s", pf.size_pretty)
    logger.info("  segmentby     : %s", pf.segmentby or "(compression off)")
    logger.info("  compress_after: %s", pf.compress_after or "(no policy)")
    logger.info(
        "  caggs         : %s",
        ", ".join(f"{c.name} ({pf.cagg_fps[c.name].rows:,} rows)" for c in pf.caggs) or "(none)",
    )


def _create_new_table(conn: Connection, pf: Preflight) -> str:
    new = f"{pf.table}{_NEW_SUFFIX}"
    conn.execute(text(f"DROP TABLE IF EXISTS {_q(pf.schema)}.{_q(new)} CASCADE"))
    # INCLUDING INDEXES carries the UNIQUE constraint's index too, which is
    # what the ingestion upserts depend on.
    conn.execute(
        text(
            f"CREATE TABLE {_q(pf.schema)}.{_q(new)} "
            f"(LIKE {_q(pf.schema)}.{_q(pf.table)} "
            f"INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"
        )
    )
    # No `partitioning_column`: dropping the space dimension is the point.
    conn.execute(
        text(
            "SELECT create_hypertable(:qualified, 'time', "
            "chunk_time_interval => CAST(:interval AS interval))"
        ),
        {"qualified": f"{pf.schema}.{new}", "interval": _CHUNK_INTERVAL},
    )
    return new


def _swap(conn: Connection, pf: Preflight, new: str) -> str:
    """Copy + drop CAGGs + rename, all in ONE transaction.

    EXCLUSIVE rather than ACCESS EXCLUSIVE: it blocks writers (which is the
    point — no row may land in the old table after the copy reads it) while
    still letting concurrent readers finish.
    """
    old = f"{pf.table}{_OLD_SUFFIX}"
    conn.execute(text(f"LOCK TABLE {_q(pf.schema)}.{_q(pf.table)} IN EXCLUSIVE MODE"))
    conn.execute(
        text(
            f"INSERT INTO {_q(pf.schema)}.{_q(new)} "  # noqa: S608
            f"SELECT * FROM {_q(pf.schema)}.{_q(pf.table)}"
        )
    )
    for c in pf.caggs:
        conn.execute(text(f"DROP MATERIALIZED VIEW {_q(pf.schema)}.{_q(c.name)}"))
    conn.execute(text(f"ALTER TABLE {_q(pf.schema)}.{_q(pf.table)} RENAME TO {_q(old)}"))
    conn.execute(text(f"ALTER TABLE {_q(pf.schema)}.{_q(new)} RENAME TO {_q(pf.table)}"))
    return old


def _restore_caggs(conn: Connection, pf: Preflight) -> None:
    for c in pf.caggs:
        opts = ["timescaledb.continuous"]
        if c.materialized_only:
            opts.append("timescaledb.materialized_only = true")
        conn.execute(
            text(
                f"CREATE MATERIALIZED VIEW {_q(pf.schema)}.{_q(c.name)} "
                f"WITH ({', '.join(opts)}) AS {c.definition} WITH NO DATA"
            )
        )
        if c.compression_enabled:
            conn.execute(
                text(
                    f"ALTER MATERIALIZED VIEW {_q(pf.schema)}.{_q(c.name)} "
                    f"SET (timescaledb.compress = true)"
                )
            )


def _refresh_caggs(engine: Engine, pf: Preflight) -> None:
    """Materialise the recreated caggs.

    On its OWN autocommit connection: `refresh_continuous_aggregate()`
    manages transactions itself and errors with `cannot run inside a
    transaction block` on the script's normal connection, which SQLAlchemy
    keeps in an implicit transaction between commits.
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as ac:
        ac.execute(text("SET statement_timeout = 0"))
        for c in pf.caggs:
            ac.execute(
                text("CALL refresh_continuous_aggregate(:view, NULL, NULL)"),
                {"view": f"{pf.schema}.{c.name}"},
            )


def _drop_hypertable_batched(conn: Connection, schema: str, table: str) -> None:
    """Drop a hypertable a few chunks at a time.

    `DROP TABLE ... CASCADE` on the old 495-chunk table takes a lock on every
    chunk, every compressed chunk, and all six indexes on each — roughly
    7,000 locks in ONE transaction. This cluster runs
    `max_locks_per_transaction = 64`, and it dies with:

        ERROR: out of shared memory
        HINT: You might need to increase max_locks_per_transaction.

    which is a restart-only setting, so batching is the fix that does not
    need a maintenance window of its own. 40 chunks per transaction leaves
    plenty of headroom.
    """
    while True:
        chunks = [
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT format('%I.%I', chunk_schema, chunk_name)
                      FROM timescaledb_information.chunks
                     WHERE hypertable_schema = :schema AND hypertable_name = :table
                     ORDER BY chunk_name
                     LIMIT 40
                    """
                ),
                {"schema": schema, "table": table},
            ).all()
        ]
        if not chunks:
            break
        for chunk in chunks:
            # `chunk` is format('%I.%I', ...) straight from the catalog.
            conn.execute(text(f"DROP TABLE IF EXISTS {chunk} CASCADE"))
        conn.commit()
        logger.info("  dropped %s chunks", len(chunks))
    conn.execute(text(f"DROP TABLE IF EXISTS {_q(schema)}.{_q(table)} CASCADE"))
    conn.commit()


def _restore_policies(conn: Connection, pf: Preflight) -> None:
    for c in pf.caggs:
        if c.refresh is None:
            continue
        start, end, schedule = c.refresh
        conn.execute(
            text(
                "SELECT add_continuous_aggregate_policy(:view, "
                "start_offset => CAST(:start AS interval), end_offset => CAST(:end AS interval), "
                "schedule_interval => CAST(:schedule AS interval), if_not_exists => true)"
            ),
            {
                "view": f"{pf.schema}.{c.name}",
                "start": start,
                "end": end,
                "schedule": schedule,
            },
        )
    if pf.segmentby:
        conn.execute(
            text(
                f"ALTER TABLE {_q(pf.schema)}.{_q(pf.table)} "
                f"SET (timescaledb.compress, "
                f"timescaledb.compress_segmentby = '{pf.segmentby}')"
            )
        )
        conn.execute(
            text(
                "SELECT count(*) FROM ("
                "  SELECT compress_chunk(c, if_not_compressed => true)"
                "    FROM show_chunks(:qualified) c) z"
            ),
            {"qualified": f"{pf.schema}.{pf.table}"},
        )
    if pf.compress_after:
        conn.execute(
            text(
                "SELECT add_compression_policy(:qualified, "
                "compress_after => CAST(:after AS interval), if_not_exists => true)"
            ),
            {"qualified": f"{pf.schema}.{pf.table}", "after": pf.compress_after},
        )


def _verify(conn: Connection, pf: Preflight) -> list[str]:
    problems: list[str] = []
    after = _fingerprint(conn, pf.schema, pf.table)
    assert pf.table_fp is not None
    if after.rows != pf.table_fp.rows:
        problems.append(f"row count {pf.table_fp.rows:,} -> {after.rows:,}")
    if after.digest != pf.table_fp.digest:
        problems.append(f"content digest changed ({pf.table_fp.digest} -> {after.digest})")
    for c in pf.caggs:
        before = pf.cagg_fps[c.name]
        now = _fingerprint(conn, pf.schema, c.name)
        if now.rows != before.rows:
            problems.append(f"{c.name}: rows {before.rows:,} -> {now.rows:,}")
        if now.digest != before.digest:
            problems.append(f"{c.name}: content digest changed")
    return problems


def _rechunk(engine: Engine, schema: str, table: str, *, drop_old: bool) -> int:
    with engine.connect() as conn:
        conn.execute(text("SET statement_timeout = 0"))
        pf = _preflight(conn, schema, table)
        _describe(pf)
        if pf.chunks <= 64:
            logger.info("only %s chunks — already right-sized, nothing to do", pf.chunks)
            return 0

        new = _create_new_table(conn, pf)
        conn.commit()
        logger.info("created %s.%s (30d chunks, no space dimension)", schema, new)

        # --- the atomic part -------------------------------------------
        old = _swap(conn, pf, new)
        conn.commit()
        logger.warning(
            "SWAPPED. %s caggs are GONE until the refresh below completes.",
            len(pf.caggs),
        )
        # ---------------------------------------------------------------

        _restore_caggs(conn, pf)
        conn.commit()
        _refresh_caggs(engine, pf)
        _restore_policies(conn, pf)
        conn.commit()
        logger.info("caggs + policies restored")

        problems = _verify(conn, pf)
        if problems:
            for p in problems:
                logger.error("VERIFY FAILED: %s", p)
            logger.error("%s.%s is left in place — investigate before dropping", schema, old)
            return 1

        after_chunks = conn.execute(
            text(
                "SELECT count(*) FROM timescaledb_information.chunks "
                " WHERE hypertable_schema = :s AND hypertable_name = :t"
            ),
            {"s": schema, "t": table},
        ).scalar_one()
        after_size = conn.execute(
            text("SELECT pg_size_pretty(hypertable_size(CAST(:q AS regclass)))"),
            {"q": f"{schema}.{table}"},
        ).scalar_one()
        logger.info(
            "VERIFIED. chunks %s -> %s, size %s -> %s, rows %s unchanged",
            pf.chunks,
            after_chunks,
            pf.size_pretty,
            after_size,
            f"{pf.rows:,}",
        )

        if drop_old:
            _drop_hypertable_batched(conn, schema, old)
            logger.info("dropped %s.%s", schema, old)
        else:
            logger.info(
                "old table kept as %s.%s — re-run with --drop-old-only to remove",
                schema,
                old,
            )
        return 0


def _drop_old_only(engine: Engine, schema: str, table: str) -> int:
    old = f"{table}{_OLD_SUFFIX}"
    with engine.connect() as conn:
        present = conn.execute(
            text("SELECT to_regclass(:q)"), {"q": f"{schema}.{old}"}
        ).scalar_one_or_none()
        if present is None:
            logger.info("%s.%s is not there — nothing to drop", schema, old)
            return 0
        conn.execute(text("SET statement_timeout = 0"))
        _drop_hypertable_batched(conn, schema, old)
    logger.info("dropped %s.%s", schema, old)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--schema", required=True, help="tenant schema name")
    parser.add_argument("--table", default="block_index_aggregates", choices=_SUPPORTED)
    parser.add_argument("--dry-run", action="store_true", help="report only, touch nothing")
    parser.add_argument("--yes", action="store_true", help="required to actually rebuild")
    parser.add_argument("--drop-old", action="store_true", help="drop the old table on success")
    parser.add_argument(
        "--drop-old-only",
        action="store_true",
        help=f"only drop a leftover <table>{_OLD_SUFFIX} and exit",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    engine = create_engine(str(get_settings().database_sync_url), future=True)
    try:
        if args.drop_old_only:
            return _drop_old_only(engine, args.schema, args.table)
        if args.dry_run:
            with engine.connect() as conn:
                _describe(_preflight(conn, args.schema, args.table))
            logger.info("dry run — nothing written")
            return 0
        if not args.yes:
            logger.error("refusing to rebuild without --yes (or use --dry-run)")
            return 2
        return _rechunk(engine, args.schema, args.table, drop_old=args.drop_old)
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
