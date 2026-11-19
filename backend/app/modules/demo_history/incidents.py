"""Steered incidents: change the stored readings so the real trees fire.

Decision D12 says the demo history is steered. The engine is never told
what to find. Instead the index readings it reads are moved, for chosen
blocks, cells and dates, the way a real problem would move them. The
replay then walks the real trees over those readings, and whatever the
trees conclude is what the history shows.

An incident has four dates. It starts to show on `start`, reaches full
strength on `full`, holds until `until`, and is gone on `gone`. The
change ramps linearly in and out, so a chart shows a decline and a
recovery rather than a step.

Index incidents move index rows only: `block_grid_aggregates` per cell
and `block_index_aggregates` per block. A `WeatherIncident` moves the
farm's own hourly temperatures and rebuilds the daily rows from them. A block's shift is the cell shift
times the share of the block's cells that the incident covers, so a
stripe of four cells in a block of thirty-three moves the block mean by
four thirty-thirds. Rasters in object storage are never touched. Their
keys are shared with every farm that has the same geometry, and a demo
must never change another tenant's pixels. The raster view of an
incident day therefore shows the real image.

Run this once, after the backfill and before the replay. Each applied
incident writes an audit row in the same transaction, and an incident
that already has one is skipped, so a second run changes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.shared.db.session import sanitize_tenant_schema

_log = get_logger(__name__)

AUDIT_EVENT = "demo_history.incident_applied"

# Value range per index, so a shift never writes an impossible reading.
_BOUNDS: dict[str, tuple[float, float]] = {
    "smi": (0.0, 1.0),
    "cwsi": (0.0, 1.0),
}
_DEFAULT_BOUNDS = (-1.0, 1.0)


@dataclass(frozen=True)
class Shift:
    """How one index moves at full strength.

    ``add`` moves every reading by `value`. ``set`` pulls every reading to
    `value`: at strength k a reading r becomes r + (value - r) * k. Use
    ``set`` when the tree tests a band rather than a floor, because an
    added shift carries the reading's own noise into the band.
    """

    index_code: str
    value: float
    mode: str = "add"

    def __post_init__(self) -> None:
        if self.mode not in ("add", "set"):
            raise ValueError(f"shift mode must be add or set, got {self.mode!r}")


@dataclass(frozen=True)
class Incident:
    """One problem on some blocks, over a span of days.

    `cells` picks the cells inside each block:

    * ``"all"``: every cell.
    * ``"cols:a-b"`` or ``"rows:a-b"``: a band of grid columns or rows,
      both ends included. A drip lateral or a sprinkler line.
    * ``"share:p"``: the first share `p` of cells by (row, col), a patch
      in one corner of the block.
    """

    code: str
    title: str
    blocks: tuple[str, ...]
    start: date
    full: date
    until: date
    gone: date
    shifts: tuple[Shift, ...]
    cells: str = "all"

    def __post_init__(self) -> None:
        if not (self.start <= self.full <= self.until < self.gone):
            raise ValueError(f"{self.code}: dates must satisfy start <= full <= until < gone")
        if not self.shifts:
            raise ValueError(f"{self.code}: an incident with no shift changes nothing")

    def weight(self, day: date) -> float:
        """Strength on `day`, from 0 to 1."""
        if day < self.start or day >= self.gone:
            return 0.0
        if day < self.full:
            return (day - self.start).days / (self.full - self.start).days
        if day <= self.until:
            return 1.0
        return (self.gone - day).days / (self.gone - self.until).days


@dataclass(frozen=True)
class WeatherIncident:
    """A cold spell on one farm's weather, over a span of days.

    The farm's hourly air temperature is pulled down so the coldest hour
    of each day reaches `min_temp_c` at full strength. The night takes the
    whole drop and the warmest hour keeps `1 - day_share` of it, so the day
    stays warmer than the night, as it does in a real cold outbreak. The
    daily summary the trees read (minimum, maximum, mean, degree days) is
    rebuilt from the moved hours.

    Weather rows live in the tenant's own schema, keyed by its own farm,
    so nothing here can reach another tenant's weather.
    """

    code: str
    title: str
    start: date
    full: date
    until: date
    gone: date
    min_temp_c: float
    day_share: float = 0.5

    def __post_init__(self) -> None:
        if not (self.start <= self.full <= self.until < self.gone):
            raise ValueError(f"{self.code}: dates must satisfy start <= full <= until < gone")
        if not 0 <= self.day_share <= 1:
            raise ValueError(f"{self.code}: day_share must be in [0, 1]")

    def weight(self, day: date) -> float:
        return Incident.weight(self, day)  # type: ignore[arg-type]


def bounds_for(index_code: str) -> tuple[float, float]:
    return _BOUNDS.get(index_code, _DEFAULT_BOUNDS)


def _cell_filter(spec: str) -> tuple[str | None, dict[str, Any]]:
    """SQL over `gc` (grid_cells) for an incident's `cells` spec.

    A share has no WHERE clause: it is a count taken from an ordered list,
    so it comes back as `(None, {"share": p})` for the caller to slice.
    """
    if spec == "all":
        return "TRUE", {}
    kind, _, rng = spec.partition(":")
    if kind in ("cols", "rows"):
        low, _, high = rng.partition("-")
        column = "gc.col_idx" if kind == "cols" else "gc.row_idx"
        return f"{column} BETWEEN :lo AND :hi", {"lo": int(low), "hi": int(high)}
    if kind == "share":
        share = float(rng)
        if not 0 < share <= 1:
            raise ValueError(f"share must be in (0, 1], got {share}")
        return None, {"share": share}
    raise ValueError(f"unknown cells spec {spec!r}")


async def _blocks(session: AsyncSession, farm_id: UUID, codes: tuple[str, ...]) -> dict[str, UUID]:
    rows = await session.execute(
        text(
            "SELECT code, id FROM blocks WHERE farm_id = :farm AND code = ANY(:codes) "
            "AND deleted_at IS NULL"
        ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
        {"farm": farm_id, "codes": list(codes)},
    )
    found = {r.code: r.id for r in rows}
    missing = set(codes) - set(found)
    if missing:
        raise ValueError(f"blocks not on this farm: {sorted(missing)}")
    return found


async def _cells(session: AsyncSession, block_id: UUID, spec: str) -> tuple[list[UUID], int]:
    """The chosen cells of the block's live grids, and the grid's cell count.

    Every live grid config of the block is included, one per product, so a
    Sentinel-2 cell and a thermal cell over the same ground move together.
    """
    base = """
        FROM grid_cells gc
        JOIN grid_configs cfg ON cfg.id = gc.grid_config_id
       WHERE cfg.block_id = :block
         AND cfg.retired_at IS NULL
         AND cfg.deleted_at IS NULL
         AND cfg.superseded_at IS NULL
    """
    params: dict[str, Any] = {"block": block_id}
    total = (
        await session.execute(
            text(f"SELECT count(*) {base}").bindparams(
                bindparam("block", type_=PG_UUID(as_uuid=True))
            ),
            params,
        )
    ).scalar_one()
    where, extra = _cell_filter(spec)
    if where is None:
        ordered = (
            (
                await session.execute(
                    text(f"SELECT gc.id {base} ORDER BY gc.row_idx, gc.col_idx").bindparams(
                        bindparam("block", type_=PG_UUID(as_uuid=True))
                    ),
                    params,
                )
            )
            .scalars()
            .all()
        )
        keep = max(1, round(len(ordered) * extra["share"]))
        return list(ordered[:keep]), int(total)
    chosen = (
        (
            await session.execute(
                text(f"SELECT gc.id {base} AND {where}").bindparams(
                    bindparam("block", type_=PG_UUID(as_uuid=True))
                ),
                {**params, **extra},
            )
        )
        .scalars()
        .all()
    )
    return list(chosen), int(total)


def _date_params(inc: Incident) -> dict[str, Any]:
    """The incident's dates as SQL parameters, one name per type.

    asyncpg gives each parameter a single type. The same `:start` used
    against the `time` column and in the day arithmetic was typed as a
    timestamp, so `d - :start` became an interval and the cast to numeric
    failed on the first run. Days are cast to date in the ramp; the row
    filter gets its own UTC timestamps.
    """
    return {
        "start": inc.start,
        "full": inc.full,
        "until": inc.until,
        "gone": inc.gone,
        "start_ts": datetime.combine(inc.start, time.min, tzinfo=UTC),
        "gone_ts": datetime.combine(inc.gone, time.min, tzinfo=UTC),
    }


# Linear ramp in SQL, the same shape as `Incident.weight`. `d` is the UTC
# day of the row.
_WEIGHT_SQL = """
    CASE
        WHEN d < CAST(:start AS date) OR d >= CAST(:gone AS date) THEN 0
        WHEN d < CAST(:full AS date)
            THEN (d - CAST(:start AS date))::numeric
                 / GREATEST(CAST(:full AS date) - CAST(:start AS date), 1)
        WHEN d <= CAST(:until AS date) THEN 1
        ELSE (CAST(:gone AS date) - d)::numeric
             / GREATEST(CAST(:gone AS date) - CAST(:until AS date), 1)
    END
"""


def _moved(column: str) -> str:
    """SQL for one column after the shift, at strength `w.k` times `:share`.

    `add` adds `:value`; `set` pulls toward `:value`. A block row takes
    the cell shift times the share of cells the incident covers.
    """
    return (
        f"CASE WHEN :set_mode "
        f"THEN {column} + (:value - {column}) * w.k * :share "
        f"ELSE {column} + :value * w.k * :share END"
    )


async def _shift_cells(
    session: AsyncSession, inc: Incident, block_id: UUID, cells: list[UUID], shift: Shift
) -> int:
    low, high = bounds_for(shift.index_code)
    result = await session.execute(
        text(
            f"""
            UPDATE block_grid_aggregates g
               SET mean = LEAST(:high, GREATEST(:low, {_moved("g.mean")})),
                   min  = LEAST(:high, GREATEST(:low, {_moved("g.min")})),
                   max  = LEAST(:high, GREATEST(:low, {_moved("g.max")}))
              FROM (
                    SELECT time, cell_id, {_WEIGHT_SQL} AS k
                      FROM (
                            SELECT time, cell_id,
                                   (time AT TIME ZONE 'UTC')::date AS d
                              FROM block_grid_aggregates
                             WHERE block_id = :block
                               AND index_code = :code
                               AND cell_id = ANY(:cells)
                               AND time >= :start_ts
                               AND time < :gone_ts
                           ) rows
                   ) w
             WHERE g.block_id = :block
               AND g.index_code = :code
               AND g.time = w.time
               AND g.cell_id = w.cell_id
               AND g.mean IS NOT NULL
               AND w.k > 0
            """  # noqa: S608 - only _WEIGHT_SQL is interpolated
        ).bindparams(
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("cells", type_=ARRAY(PG_UUID(as_uuid=True))),
        ),
        {
            "block": block_id,
            "code": shift.index_code,
            "cells": cells,
            "value": shift.value,
            "set_mode": shift.mode == "set",
            "share": 1.0,
            "low": low,
            "high": high,
            **_date_params(inc),
        },
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def _shift_block(
    session: AsyncSession, inc: Incident, block_id: UUID, share: float, shift: Shift
) -> int:
    low, high = bounds_for(shift.index_code)
    columns = ("mean", "min", "max", "p10", "p50", "p90")
    sets = ",\n".join(f"{c} = LEAST(:high, GREATEST(:low, {_moved(f'a.{c}')}))" for c in columns)
    result = await session.execute(
        text(
            f"""
            UPDATE block_index_aggregates a
               SET {sets}
              FROM (
                    SELECT time, product_id, {_WEIGHT_SQL} AS k
                      FROM (
                            SELECT time, product_id,
                                   (time AT TIME ZONE 'UTC')::date AS d
                              FROM block_index_aggregates
                             WHERE block_id = :block
                               AND index_code = :code
                               AND time >= :start_ts
                               AND time < :gone_ts
                           ) rows
                   ) w
             WHERE a.block_id = :block
               AND a.index_code = :code
               AND a.time = w.time
               AND a.product_id = w.product_id
               AND a.mean IS NOT NULL
               AND w.k > 0
            """  # noqa: S608 - only constants are interpolated
        ).bindparams(bindparam("block", type_=PG_UUID(as_uuid=True))),
        {
            "block": block_id,
            "code": shift.index_code,
            "value": shift.value,
            "set_mode": shift.mode == "set",
            "share": share,
            "low": low,
            "high": high,
            **_date_params(inc),
        },
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def apply_weather_incident(
    session: AsyncSession, farm_id: UUID, inc: WeatherIncident
) -> dict[str, int]:
    """Move the farm's hourly temperatures, then rebuild the daily rows."""
    params: dict[str, Any] = {
        "farm": farm_id,
        "target": inc.min_temp_c,
        "day_share": inc.day_share,
        **_date_params(inc),  # type: ignore[arg-type]
    }
    moved = await session.execute(
        text(
            f"""
            WITH day AS (
                SELECT (time AT TIME ZONE 'UTC')::date AS d, provider_code,
                       min(air_temp_c) AS tmin, max(air_temp_c) AS tmax
                  FROM weather_observations
                 WHERE farm_id = :farm
                   AND time >= :start_ts AND time < :gone_ts
                   AND air_temp_c IS NOT NULL
                 GROUP BY 1, 2
            ), w AS (
                SELECT d, provider_code, tmin, tmax, {_WEIGHT_SQL} AS k FROM day
            )
            UPDATE weather_observations o
               SET air_temp_c = o.air_temp_c
                   + LEAST(0, CAST(:target AS numeric) - w.tmin) * w.k
                     * (1 - CAST(:day_share AS numeric)
                            * COALESCE((o.air_temp_c - w.tmin) / NULLIF(w.tmax - w.tmin, 0), 0))
              FROM w
             WHERE o.farm_id = :farm
               AND (o.time AT TIME ZONE 'UTC')::date = w.d
               AND o.provider_code = w.provider_code
               AND o.air_temp_c IS NOT NULL
               AND w.k > 0
            """  # noqa: S608 - only _WEIGHT_SQL is interpolated
        ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
        params,
    )
    hours = int(getattr(moved, "rowcount", 0) or 0)

    # Rebuild the moved days' summaries from the hours, keeping how the
    # derivation computes them: the mean is the hourly mean and degree days
    # are the mean above the base.
    old = {
        r.date: r.gdd
        for r in await session.execute(
            text(
                "SELECT date, gdd_base10 AS gdd FROM weather_derived_daily "
                "WHERE farm_id = :farm AND date >= :start AND date < :gone"
            ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
            params,
        )
    }
    rebuilt = await session.execute(
        text(
            """
            UPDATE weather_derived_daily d
               SET temp_min_c = h.tmin, temp_max_c = h.tmax, temp_mean_c = h.tmean,
                   gdd_base10 = GREATEST(0, h.tmean - 10),
                   gdd_base15 = GREATEST(0, h.tmean - 15)
              FROM (
                    SELECT (time AT TIME ZONE 'UTC')::date AS day,
                           round(min(air_temp_c), 2) AS tmin,
                           round(max(air_temp_c), 2) AS tmax,
                           round(avg(air_temp_c), 2) AS tmean
                      FROM weather_observations
                     WHERE farm_id = :farm
                       AND time >= :start_ts AND time < :gone_ts
                       AND air_temp_c IS NOT NULL
                     GROUP BY 1
                   ) h
             WHERE d.farm_id = :farm AND d.date = h.day
            RETURNING d.date, d.gdd_base10
            """
        ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
        params,
    )
    delta = {r.date: (r.gdd_base10 or 0) - (old.get(r.date) or 0) for r in rebuilt}

    # The season's running total drops by what the cold days lost, from the
    # first moved day until the total resets for a new season.
    seasonal = 0
    if delta:
        rows = (
            await session.execute(
                text(
                    "SELECT date, gdd_cumulative_base10_season AS cum "
                    "FROM weather_derived_daily WHERE farm_id = :farm AND date >= :start "
                    "ORDER BY date"
                ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                params,
            )
        ).all()
        running = 0
        previous = None
        for row in rows:
            if previous is not None and row.cum is not None and row.cum < previous:
                break  # a new season starts from zero
            previous = row.cum
            running += delta.get(row.date, 0)
            if running and row.cum is not None:
                await session.execute(
                    text(
                        "UPDATE weather_derived_daily "
                        "SET gdd_cumulative_base10_season = GREATEST(0, CAST(:v AS numeric)) "
                        "WHERE farm_id = :farm AND date = :d"
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"v": row.cum + running, "farm": farm_id, "d": row.date},
                )
                seasonal += 1

    counts = {"weather_hours": hours, "weather_days": len(delta), "season_rows": seasonal}
    await _audit(session, farm_id, inc, counts)
    _log.info("demo_history_weather_incident_applied", code=inc.code, **counts)
    return counts


async def _audit(
    session: AsyncSession, farm_id: UUID, inc: Incident | WeatherIncident, counts: dict[str, int]
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO audit_events
                (time, id, event_type, actor_user_id, actor_kind, subject_kind,
                 subject_id, farm_id, details)
            VALUES (clock_timestamp(), :id, :ev, NULL, 'system', 'farm',
                    :farm, :farm, CAST(:details AS jsonb))
            """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid4(),
            "ev": AUDIT_EVENT,
            "farm": farm_id,
            "details": _details_json(inc, counts),
        },
    )


async def already_applied(session: AsyncSession, farm_id: UUID) -> set[str]:
    rows = await session.execute(
        text(
            "SELECT details->>'code' AS code FROM audit_events "
            "WHERE event_type = :ev AND farm_id = :farm"
        ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
        {"ev": AUDIT_EVENT, "farm": farm_id},
    )
    return {r.code for r in rows}


async def apply_incident(session: AsyncSession, farm_id: UUID, inc: Incident) -> dict[str, int]:
    """Apply one incident inside the caller's transaction.

    Returns the rows moved, per table. The caller commits, and the audit
    row written here commits with the data, so a crash leaves neither.
    """
    blocks = await _blocks(session, farm_id, inc.blocks)
    counts = {"cell_rows": 0, "block_rows": 0}
    for code in inc.blocks:
        block_id = blocks[code]
        cells, total = await _cells(session, block_id, inc.cells)
        share = (len(cells) / total) if total else 1.0
        for shift in inc.shifts:
            if cells:
                counts["cell_rows"] += await _shift_cells(session, inc, block_id, cells, shift)
            counts["block_rows"] += await _shift_block(session, inc, block_id, share, shift)
    await _audit(session, farm_id, inc, counts)
    _log.info("demo_history_incident_applied", code=inc.code, **counts)
    return counts


def _details_json(inc: Incident | WeatherIncident, counts: dict[str, int]) -> str:
    what: dict[str, Any]
    if isinstance(inc, WeatherIncident):
        what = {"weather": {"min_temp_c": inc.min_temp_c, "day_share": inc.day_share}}
    else:
        what = {
            "blocks": list(inc.blocks),
            "cells": inc.cells,
            "shifts": {s.index_code: [s.mode, s.value] for s in inc.shifts},
        }
    return json.dumps(
        {
            "code": inc.code,
            "title": inc.title,
            **what,
            "start": inc.start.isoformat(),
            "full": inc.full.isoformat(),
            "until": inc.until.isoformat(),
            "gone": inc.gone.isoformat(),
            **counts,
        }
    )


async def apply_scenario(
    session_factory: Any, tenant_schema: str, scenario: Any, *, dry_run: bool = False
) -> list[dict[str, Any]]:
    """Apply every incident of `scenario` that has not been applied yet.

    `scenario` is a module with `FARM_CODE` and `INCIDENTS`, and optionally
    `WEATHER_INCIDENTS`. Each incident
    commits on its own with its audit row, so a failure part way leaves the
    earlier ones applied and a second call applies only what is left.
    Returns one entry per incident: its code, whether it was skipped, and
    the rows it moved.
    """
    safe = sanitize_tenant_schema(tenant_schema)
    async with session_factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
        farm_id = (
            await session.execute(
                text("SELECT id FROM farms WHERE code = :c AND deleted_at IS NULL"),
                {"c": scenario.FARM_CODE},
            )
        ).scalar_one_or_none()
        if farm_id is None:
            raise ValueError(f"no farm with code {scenario.FARM_CODE} in {tenant_schema}")
        done = await already_applied(session, farm_id)

    results: list[dict[str, Any]] = []
    weather = tuple(getattr(scenario, "WEATHER_INCIDENTS", ()))
    for inc in (*scenario.INCIDENTS, *weather):
        if inc.code in done:
            results.append({"code": inc.code, "skipped": True})
            continue
        async with session_factory() as session:
            await session.begin()
            await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
            if isinstance(inc, WeatherIncident):
                counts = await apply_weather_incident(session, farm_id, inc)
            else:
                counts = await apply_incident(session, farm_id, inc)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        results.append({"code": inc.code, "skipped": False, **counts})
    return results
