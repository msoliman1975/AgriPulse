"""Clone a real tenant's *inputs* into a throwaway simulation tenant.

Act 2 of a simulation run needs two farms whose data looks like a real
customer's: real geometry, a realistic block layout, and enough observation
history that decision trees have something to fire on. Inventing that by hand
produces data whose distribution nothing recognises. Cloning a live tenant
produces data that behaves.

Inputs, never outputs
---------------------
The manifest below copies geometry, configuration, crop assignments and
observation history. It deliberately copies **no** alerts, recommendations,
irrigation schedules, plans or evaluation runs.

That is the single most important rule here. Act 3 triggers evaluation and
then asserts that recommendations and alerts appeared. If the clone had
brought them along, that assertion would pass on cloned rows and prove
nothing — the harness would report a working pipeline while the pipeline was
dead. Clone what the pipeline reads; let the pipeline write the rest.

Sanitisation happens at extract, not at load
--------------------------------------------
Names, codes and identifiers are replaced while reading the source, so the
snapshot itself contains no customer identifiers. A snapshot is written once
to object storage and replayed for every run (see the module docstring rule in
``docs/testing/org-simulation-harness.md``): a file that sat in a bucket
carrying a real customer's farm names and row ids would be a copy of their
data, however it was labelled.

Identifiers are remapped rather than preserved. Row ids are only unique within
a tenant schema, but ``public.farm_scopes`` and ``public.backfill_runs``
reference ``farm_id`` across schemas, so two tenants holding the same farm id
would collide platform-wide. The remap is built from the primary keys of the
cloned rows themselves, which is what makes it safe: a UUID that is not the id
of something we cloned — a crop, an imagery product, a weather provider — is
not in the map and passes through untouched, still pointing at the platform
catalog row it always did.

Columns come from ``information_schema``
----------------------------------------
Nothing here hardcodes a column list. The stated risk of cloning a real tenant
is that its shape changes and the seed silently changes with it; reading the
live columns and reporting the difference at load time is what makes that
visible instead of silent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.db.session import sanitize_tenant_schema

# 2: `latest_observed_at` excludes forward-looking tables. The file layout is
# unchanged from 1, so the bump buys nothing structural -- it exists so a v1
# file is REFUSED rather than loaded. A v1 snapshot's `latest_observed_at` is
# its forecast horizon, and loading one rebases the whole seed days into the
# past while leaving no forecast ahead of the run: a seed that looks fine,
# loads without error, and quietly starves every tree of recent data. Re-run
# `sim_snapshot.py extract` to get a v2 file.
SNAPSHOT_VERSION = 2


@dataclass(frozen=True)
class ClonedTable:
    """One table the clone carries, and what has to change on the way through."""

    name: str
    #: Ascending; parents before children so FKs resolve on insert.
    order: int
    #: Columns replaced with a deterministic placeholder at extract time.
    #: Anything free-text that a human may have typed into.
    redact: tuple[str, ...] = ()
    #: Columns forced to a constant on load. Subscriptions are copied as rows
    #: so the configuration is faithful, but inactive so that loading a
    #: snapshot never starts a real provider fetching real imagery.
    force: dict[str, Any] = field(default_factory=dict)
    #: Rows are dropped when this column is not NULL — used to leave a source
    #: tenant's archived entities behind rather than resurrect them.
    skip_when_set: str | None = None
    #: The observation-time column, set only on history tables. Naming it is
    #: what makes the rebase offset correct: these tables also carry
    #: `inserted_at`/`created_at`, which sit at ~now and would peg the offset
    #: to the extract date, leaving the real history months in the past where
    #: no tree finds recent data. Guessing metadata column names by pattern
    #: is how that bug got written in the first place.
    history: str | None = None
    #: This table's `history` column points *forward* of the extract date, so
    #: it is rebased like any other but must never be what CHOOSES the offset.
    #: A forecast horizon runs days ahead of the newest real observation;
    #: letting it define "now" pushes the whole seed that far into the past and
    #: lands every forecast row behind `as_of`, leaving the tenant with no
    #: forward forecast at all. Same failure as the `inserted_at` trap above,
    #: from the opposite direction.
    forward_looking: bool = False
    note: str = ""


# Ordered parents-first. `blocks` self-references through parent_unit_id, so
# sub-blocks are ordered after their parents inside the table by the extract.
CLONE_TABLES: tuple[ClonedTable, ...] = (
    ClonedTable(
        "farms",
        order=10,
        redact=("name", "code", "notes", "description"),
        skip_when_set="deleted_at",
    ),
    ClonedTable(
        "blocks",
        order=20,
        redact=("name", "code", "notes", "description"),
        skip_when_set="deleted_at",
    ),
    ClonedTable(
        "block_crops",
        order=30,
        note="crop assignment + phenology; crop ids point at the platform catalog",
    ),
    ClonedTable("grid_configs", order=30),
    ClonedTable("grid_cells", order=40),
    ClonedTable(
        "weather_subscriptions",
        order=30,
        force={"is_active": False},
        note="configuration only — an active row would start fetching on load",
    ),
    ClonedTable(
        "imagery_aoi_subscriptions",
        order=30,
        force={"is_active": False},
        note="configuration only — an active row would start fetching on load",
    ),
    # The farm-level halves. Without these a cloned tenant loses the
    # configuration of every farm that has cut over to whole-farm fetching —
    # and thermal entirely, since `landsat_c2_l2_st` is farm-AOI only and has
    # no block rows to fall back on. The clone would look configured (block
    # rows present) while describing a farm that fetches nothing.
    ClonedTable(
        "imagery_farm_subscriptions",
        order=30,
        force={"is_active": False},
        note="configuration only — an active row would start fetching on load",
    ),
    ClonedTable(
        "weather_farm_subscriptions",
        order=30,
        force={"is_active": False},
        note="configuration only — an active row would start fetching on load",
    ),
    # --- observation history: what the pipeline reads -----------------------
    ClonedTable("weather_observations", order=50, history="time"),
    ClonedTable(
        "weather_forecasts",
        order=50,
        history="time",
        forward_looking=True,
        note="horizon runs ahead of today; rebased by the offset, never sets it",
    ),
    ClonedTable(
        "block_index_aggregates",
        order=50,
        history="time",
        note="the index history decision trees actually evaluate against",
    ),
)

# Everything below is an *output* of the pipeline the run is meant to exercise,
# or is authored by a real person. Listed rather than merely absent, so the
# reason survives someone wondering why the clone looks incomplete.
DELIBERATELY_NOT_CLONED: dict[str, str] = {
    "alerts": "an output; Act 3 must produce these or the run proved nothing",
    "recommendations": "an output; same",
    "recommendations_history": "an output; same",
    "decision_tree_eval_runs": "an output; same",
    "decision_tree_eval_traces": "an output; same",
    "irrigation_schedules": "an output of irrigation.generate_for_tenant",
    "weather_derived_daily": "an output of weather.derive_weather_daily",
    "weather_index_daily": "an output of the projection task",
    "weather_index_baselines": "an output of the baseline sweep",
    "block_index_baselines": "an output of indices.recompute_baselines_for_tenant",
    "weather_risk_daily": "an output of weather.compute_risk_for_tenant",
    "block_water_balance_daily": "an output of the water-balance task",
    "vegetation_plans": "an output; the Owner persona assigns plans in Act 2",
    "plan_activities": "an output; same",
    "signal_observations": "authored by real scouts in the field",
    "scouting_visits": "authored by real people, and names them",
    "scouting_routing_rules": "names real assignees",
    "resources": "real workers and equipment, i.e. named people",
    "resource_farms": "same",
    "block_responsible_log": "names real people",
    "growth_stage_logs": "history of an output; block_crops carries the stage",
    "farm_attachments": "points at real files in object storage",
    "block_attachments": "same",
    "notification_dispatches": "an output, and carries real addresses",
    "in_app_inbox": "an output, and per-user",
    "weather_ingestion_attempts": "operational log of the source tenant",
    "audit_events": "the source tenant's audit trail",
}


class SnapshotError(RuntimeError):
    """The snapshot cannot be produced or applied as asked."""


# --- extract ----------------------------------------------------------------


async def extract(
    session: AsyncSession,
    *,
    source_schema: str,
    farm_limit: int | None = None,
) -> dict[str, Any]:
    """Read a sanitised, identifier-remapped snapshot of one tenant's inputs.

    ``farm_limit`` keeps a snapshot to the first N farms, which is what makes a
    run cheap: Bashayer has far more history than two simulated farms need.
    """
    schema = sanitize_tenant_schema(source_schema)
    remap: dict[UUID, UUID] = {}
    tables: dict[str, Any] = {}

    farm_ids = await _farm_ids(session, schema, farm_limit)
    if not farm_ids:
        raise SnapshotError(f"{schema} has no live farms to clone")
    block_ids = await _block_ids(session, schema, farm_ids)

    for spec in sorted(CLONE_TABLES, key=lambda t: (t.order, t.name)):
        columns = await _columns(session, schema, spec.name)
        if not columns:
            # A table absent from the source is reported, not fatal: the source
            # may simply predate a migration this deployment has.
            tables[spec.name] = {"missing": True, "columns": [], "rows": []}
            continue
        rows = await _read_rows(
            session, schema, spec, columns, farm_ids=farm_ids, block_ids=block_ids
        )
        tables[spec.name] = {
            "missing": False,
            "columns": [c["name"] for c in columns],
            "geometry_columns": [c["name"] for c in columns if c["is_geometry"]],
            # Arrays and JSONB both come back as Python lists. Only JSONB may
            # be re-serialised on insert; handing a JSON string to a text[]
            # column is a type error, not a conversion.
            "json_columns": [c["name"] for c in columns if c["is_json"]],
            # Dates travel as ISO strings and have to be rebuilt: asyncpg binds
            # a date column strictly and will not parse one for us.
            "date_columns": [c["name"] for c in columns if c["is_date"]],
            "rows": rows,
        }

    # Pass 1 collected nothing until now: the id map is built from the primary
    # keys of what was actually read, so a UUID that is not one of our own row
    # ids (a crop, a product, a provider) is absent from the map and survives
    # unchanged, still pointing at the platform catalog.
    for payload in tables.values():
        for row in payload["rows"]:
            raw = row.get("id")
            if isinstance(raw, str) and _is_uuid(raw):
                remap.setdefault(UUID(raw), uuid4())

    latest = _latest_timestamp(tables)
    for name, payload in tables.items():
        spec = _spec(name)
        payload["rows"] = [_rewrite(row, remap) for row in payload["rows"]]
        payload["rows"] = _redact_rows(name, payload["rows"], spec)

    return {
        "snapshot_version": SNAPSHOT_VERSION,
        # Recorded for provenance, not for reconnection: nothing in a load
        # path reads it back.
        "source_schema": schema,
        "extracted_at": datetime.now(UTC).isoformat(),
        "latest_observed_at": latest.isoformat() if latest else None,
        "farm_count": len(farm_ids),
        "block_count": len(block_ids),
        "tables": tables,
        "not_cloned": DELIBERATELY_NOT_CLONED,
    }


async def _farm_ids(session: AsyncSession, schema: str, limit: int | None) -> list[UUID]:
    sql = (
        f'SELECT id FROM "{schema}".farms WHERE deleted_at IS NULL ORDER BY code, id'  # noqa: S608
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in await session.execute(text(sql))]


async def _block_ids(session: AsyncSession, schema: str, farm_ids: list[UUID]) -> list[UUID]:
    rows = await session.execute(
        text(
            f'SELECT id FROM "{schema}".blocks '  # noqa: S608
            f"WHERE farm_id = ANY(:ids) AND deleted_at IS NULL"
        ),
        {"ids": farm_ids},
    )
    return [r[0] for r in rows]


async def _columns(session: AsyncSession, schema: str, table: str) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            # Generated columns cannot be inserted into, and carry nothing a
            # snapshot needs: Postgres recomputes them from the columns that
            # are carried.
            "AND is_generated = 'NEVER' "
            "ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    )
    return [
        {
            "name": r["column_name"],
            "is_geometry": r["udt_name"] in ("geometry", "geography"),
            "is_json": r["udt_name"] in ("json", "jsonb"),
            "is_date": r["udt_name"] == "date",
        }
        for r in rows.mappings().all()
    ]


async def _read_rows(
    session: AsyncSession,
    schema: str,
    spec: ClonedTable,
    columns: list[dict[str, Any]],
    *,
    farm_ids: list[UUID],
    block_ids: list[UUID],
) -> list[dict[str, Any]]:
    names = {c["name"] for c in columns}
    # Geometry has no JSON representation, so it travels as EWKT and is rebuilt
    # on load. Keeping the SRID is the point of the E.
    selected = ", ".join(
        f'ST_AsEWKT("{c["name"]}") AS "{c["name"]}"' if c["is_geometry"] else f'"{c["name"]}"'
        for c in columns
    )
    if "farm_id" in names:
        where, params = "farm_id = ANY(:fids)", {"fids": farm_ids}
    elif "block_id" in names:
        where, params = "block_id = ANY(:bids)", {"bids": block_ids}
    elif spec.name == "farms":
        where, params = "id = ANY(:fids)", {"fids": farm_ids}
    elif spec.name == "grid_cells":
        where, params = (
            f'grid_config_id IN (SELECT id FROM "{schema}".grid_configs '  # noqa: S608
            f"WHERE block_id = ANY(:bids))",
            {"bids": block_ids},
        )
    else:
        raise SnapshotError(f"{spec.name}: no farm_id/block_id column and no explicit scope")

    if spec.skip_when_set and spec.skip_when_set in names:
        where += f' AND "{spec.skip_when_set}" IS NULL'

    result = await session.execute(
        text(f'SELECT {selected} FROM "{schema}"."{spec.name}" WHERE {where}'),  # noqa: S608
        params,
    )
    return [{k: _encode(v) for k, v in row.items()} for row in result.mappings().all()]


def _encode(value: Any) -> Any:
    """JSON-safe representation that survives a round trip through storage."""
    if isinstance(value, datetime):
        return value.isoformat()
    # After the datetime branch: every datetime is also a date, not the
    # reverse. Plain dates are deliberately not rebased -- active_from and
    # established_date describe the entity, not the observation history, and
    # shifting them would move a farm's activation relative to nothing.
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # str, not float: these are agronomic measurements and index values,
        # and float would quietly change them.
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict | list):
        return json.loads(json.dumps(value, default=str))
    return value


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _rewrite(row: dict[str, Any], remap: dict[UUID, UUID]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, str) and _is_uuid(value):
            mapped = remap.get(UUID(value))
            out[key] = str(mapped) if mapped else value
        else:
            out[key] = value
    return out


def _spec(name: str) -> ClonedTable:
    for spec in CLONE_TABLES:
        if spec.name == name:
            return spec
    raise SnapshotError(f"{name} is not in the clone manifest")


def _redact_rows(name: str, rows: list[dict[str, Any]], spec: ClonedTable) -> list[dict[str, Any]]:
    """Replace human-authored text with positional placeholders.

    Farms become ``SIM-F01``, blocks ``SIM-B01``. Readable enough that a
    persona can talk about a block, and carrying nothing of the original.
    Free-text columns are blanked rather than relabelled — a note is the
    likeliest place for a customer's name to be sitting.
    """
    if not spec.redact:
        return rows
    prefix = "F" if name == "farms" else "B"
    for index, row in enumerate(rows, start=1):
        label = f"SIM-{prefix}{index:02d}"
        for column in spec.redact:
            if column not in row:
                continue
            row[column] = label if column in ("name", "code") else None
    return rows


def _latest_timestamp(tables: dict[str, Any]) -> datetime | None:
    """Newest *observation* across the history tables.

    One value for the whole snapshot, because the load rebases everything by a
    single offset. Rebasing each table against its own maximum would slide
    weather and imagery apart, and a tree comparing the two would then be
    reading a correlation the source never had.

    Observation means observed: `forward_looking` tables are skipped. A
    forecast horizon sits days ahead of the newest real reading, and it once
    won this comparison outright -- which silently aged the whole seed by the
    length of the horizon and left no forecast in front of the run.
    """
    latest: datetime | None = None
    for name, payload in tables.items():
        spec = _spec(name)
        column = spec.history
        if column is None or spec.forward_looking:
            continue
        for row in payload["rows"]:
            parsed = _as_datetime(row.get(column))
            if parsed is not None and (latest is None or parsed > latest):
                latest = parsed
    return latest


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) < 19 or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# --- load -------------------------------------------------------------------


async def load(
    session: AsyncSession,
    *,
    target_schema: str,
    snapshot: dict[str, Any],
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Apply a snapshot to an empty tenant schema, rebased onto ``as_of``.

    Every timestamp shifts by one offset, chosen so the newest observation in
    the snapshot lands one day before ``as_of``. That is what makes the tenant
    "born mid-season": the trees see history behind them and today in front.
    """
    schema = sanitize_tenant_schema(target_schema)
    if int(snapshot.get("snapshot_version", 0)) != SNAPSHOT_VERSION:
        raise SnapshotError(
            f"snapshot version {snapshot.get('snapshot_version')} "
            f"!= supported {SNAPSHOT_VERSION}"
        )

    offset = _offset_for(snapshot, as_of or datetime.now(UTC))
    report: dict[str, Any] = {
        "target_schema": schema,
        "offset_days": round(offset.total_seconds() / 86400, 2),
        "tables": {},
        "dropped_columns": {},
        "missing_in_source": [],
    }

    for spec in sorted(CLONE_TABLES, key=lambda t: (t.order, t.name)):
        payload = snapshot["tables"].get(spec.name)
        if payload is None or payload.get("missing"):
            report["missing_in_source"].append(spec.name)
            continue
        target_columns = {c["name"] for c in await _columns(session, schema, spec.name)}
        if not target_columns:
            raise SnapshotError(f'"{schema}".{spec.name} does not exist')

        usable = [c for c in payload["columns"] if c in target_columns]
        # Drift is reported rather than swallowed: a column the source had and
        # the target does not is the "seeds changed silently" failure this
        # whole tool was warned about.
        dropped = sorted(set(payload["columns"]) - target_columns)
        if dropped:
            report["dropped_columns"][spec.name] = dropped

        inserted = await _insert_rows(
            session,
            schema=schema,
            spec=spec,
            columns=usable,
            geometry=set(payload.get("geometry_columns") or ()),
            json_columns=set(payload.get("json_columns") or ()),
            date_columns=set(payload.get("date_columns") or ()),
            rows=payload["rows"],
            offset=offset,
        )
        report["tables"][spec.name] = inserted

    return report


def _offset_for(snapshot: dict[str, Any], as_of: datetime) -> timedelta:
    latest = snapshot.get("latest_observed_at")
    if not latest:
        return timedelta(0)
    parsed = _as_datetime(latest)
    if parsed is None:
        return timedelta(0)
    return (as_of - timedelta(days=1)) - parsed


def _rebase(value: datetime, offset: timedelta) -> datetime:
    """Shift an observation — but leave an open-ended valid-time bound alone.

    The valid-time columns use the extremes of the datetime range as sentinels:
    ``grid_configs.effective_from`` is ``0001-01-01`` for "has always applied",
    and the matching upper bounds sit at the maximum for "still applies". Those
    are markers, not observations. Rebasing one says nothing — "always" does
    not move when the season does — and rebasing the lower one raises
    ``OverflowError: date value out of range`` outright, which is how this was
    found: the first real load died on `grid_configs` with a negative offset.

    The try/except is a backstop, not the rule. Any timestamp close enough to
    either extreme to overflow is a sentinel by construction; nothing that
    describes a real observation lives within days of year 1 or year 9999.
    """
    if value.date() in (datetime.min.date(), datetime.max.date()):
        return value
    try:
        return value + offset
    except OverflowError:
        return value


async def _insert_rows(
    session: AsyncSession,
    *,
    schema: str,
    spec: ClonedTable,
    columns: list[str],
    geometry: set[str],
    json_columns: set[str],
    date_columns: set[str],
    rows: list[dict[str, Any]],
    offset: timedelta,
) -> int:
    if not rows:
        return 0
    placeholders = ", ".join(
        f"ST_GeomFromEWKT(:{c})" if c in geometry else f":{c}" for c in columns
    )
    quoted = ", ".join(f'"{c}"' for c in columns)
    stmt = text(
        f'INSERT INTO "{schema}"."{spec.name}" ({quoted}) VALUES ({placeholders})'  # noqa: S608
    )

    count = 0
    for row in rows:
        params: dict[str, Any] = {}
        for column in columns:
            value = spec.force.get(column, row.get(column))
            if column not in spec.force:
                shifted = _as_datetime(value)
                if shifted is not None:
                    value = _rebase(shifted, offset)
            if column in date_columns and isinstance(value, str):
                value = date.fromisoformat(value)
            if column in json_columns and isinstance(value, dict | list):
                value = json.dumps(value)
            params[column] = value
        await session.execute(stmt, params)
        count += 1
    return count


__all__ = [
    "CLONE_TABLES",
    "DELIBERATELY_NOT_CLONED",
    "SNAPSHOT_VERSION",
    "ClonedTable",
    "SnapshotError",
    "extract",
    "load",
]
