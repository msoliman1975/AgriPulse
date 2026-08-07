"""Map-experience block summary endpoint.

Single call returns one row per active block in a farm with the data the
map-first frontend needs to color polygons + show alert badges:

  GET /api/v1/farms/{farm_id}/blocks/summary

  → { farm_id, as_of, units: [{
        id, health, alert_count, alert_severity,
        ndvi_current, ndre_current, ndwi_current,
        last_index_at,
      }, ...] }

Designed to replace ~Nx4 round-trips (per-block detail + per-block-per-
index timeseries + tenant-wide alert list) the prototype was making for
N blocks. Three SQL queries against the tenant schema (alerts, the block
roster, and the latest index values), plus a fourth only when a block has
no reading inside the recent window — see `_RECENT_WINDOW_DAYS`.

Health classification mirrors what the frontend used to do:
  critical alert → critical
  warning alert → watch
  ndvi < 0.4    → critical (only when no overriding alert)
  ndvi < 0.55   → watch
  otherwise     → healthy
  no data       → unknown

Caching: deferred. The prototype exercises this from the polling loop
(60s interval); add Redis with a 60s TTL when the validation cohort
grows past a single tester.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import RequestContext
from app.shared.db.session import get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["farms"])


# Indices the map surfaces. Backend has no NDMI; NDWI is the closest
# moisture-related index available — see the frontend api.ts for the
# matching substitution. Add NDMI to this tuple once the imagery
# pipeline starts computing it.
_MAP_INDICES: tuple[str, ...] = ("ndvi", "ndre", "ndwi")

# How far back the *first* pass of the latest-value lookup looks.
#
# `block_index_aggregates` is a TimescaleDB hypertable. "Latest value per
# (block, index)" has no natural time bound, and without a predicate on
# `time` TimescaleDB cannot exclude chunks, so it plans every chunk in the
# table. Measured on prod 2026-08-05 (36-block farm, 494 chunks holding
# 49k rows): planning 645-1039 ms against execution 190-224 ms — the cost
# was almost entirely *planning*, and it grew with every week of history
# rather than with the amount of data.
#
# Bounding the scan restores chunk exclusion: 494 chunks -> 72, and the
# whole query goes 875 ms -> 36 ms (23 ms planning + 13 ms execution).
#
# Blocks that return nothing in the window fall back to an unbounded
# lookup (`_latest_indices`), so a dormant block still shows its last
# known reading and this is not a behaviour change for them. Migration
# 0057 additionally right-sizes the chunking so the fallback path stops
# degrading as history accumulates.
_RECENT_WINDOW_DAYS = 120

Health = Literal["healthy", "watch", "critical", "unknown"]
MapSeverity = Literal["watch", "critical"]


class BlockSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    health: Health
    alert_count: int
    alert_severity: MapSeverity | None
    ndvi_current: float | None
    ndre_current: float | None
    ndwi_current: float | None
    last_index_at: datetime | None
    # The imagery product this block's sub-block grid is configured against,
    # or null when it has no grid. The map turns its grid overlay on by
    # default when ANY block in the farm carries one, and fetches cells only
    # for the blocks that do — without this it would have to ask every block
    # for its subscriptions first, N requests before drawing anything.
    grid_product_id: UUID | None = None


class BlocksSummaryResponse(BaseModel):
    farm_id: UUID
    as_of: datetime
    units: list[BlockSummary]


# Latest non-null value per (block, index).
#
# The time bound is interpolated into the SQL as a literal interval rather
# than bound as a parameter, and that is load-bearing: TimescaleDB excludes
# chunks at *plan* time, which it can only do when the cutoff is a
# plan-time constant. Measured both ways on prod, same farm, same rows:
#
#   ... a.time > now() - make_interval(days => $3)   ->  705 ms planning
#   ... a.time > now() - interval '120 days'         ->   23 ms planning
#
# A bound cutoff produces a generic plan over all 494 chunks and the fix
# evaporates. `_RECENT_WINDOW_DAYS` is a module constant, never user input,
# so interpolating it carries no injection surface.
def _latest_indices_sql(*, cutoff_days: int | None) -> str:
    window = "" if cutoff_days is None else f"AND a.time > now() - interval '{cutoff_days} days'"
    return f"""
        SELECT DISTINCT ON (a.block_id, a.index_code)
               a.block_id,
               a.index_code,
               a.mean,
               a.time
        FROM block_index_aggregates a
        WHERE a.block_id = ANY(:block_ids)
          AND a.index_code = ANY(:codes)
          AND a.mean IS NOT NULL
          {window}
        ORDER BY a.block_id, a.index_code, a.time DESC
    """


# Binds are typed explicitly: asyncpg infers nothing from a bare `text()`
# placeholder, and an untyped bind reaching an array comparison is the
# shape that has produced DataError in prod before.
def _latest_indices_stmt(*, cutoff_days: int | None) -> Any:
    return text(_latest_indices_sql(cutoff_days=cutoff_days)).bindparams(
        bindparam("block_ids", type_=ARRAY(PG_UUID(as_uuid=True))),
        bindparam("codes", type_=ARRAY(Text())),
    )


_RECENT_STMT = _latest_indices_stmt(cutoff_days=_RECENT_WINDOW_DAYS)
_UNBOUNDED_STMT = _latest_indices_stmt(cutoff_days=None)


async def _latest_indices(
    session: AsyncSession, block_ids: list[UUID]
) -> dict[UUID, dict[str, tuple[float, datetime]]]:
    """Latest value + time per (block, index), keyed by block id.

    Two passes. The first is bounded to `_RECENT_WINDOW_DAYS` so
    TimescaleDB can exclude chunks (see that constant for the numbers).
    Any block the window turned up nothing for — a block whose imagery
    stopped long ago, or one being backfilled — is swept again without a
    bound, so it still reports its last known reading.

    The fallback is per-block, not per-(block, index): a block that has
    *any* recent reading keeps only its in-window values. Indices are
    computed together from the same scene, so a block with recent NDVI but
    year-old NDRE isn't a shape the pipeline produces.
    """
    if not block_ids:
        return {}

    out: dict[UUID, dict[str, tuple[float, datetime]]] = {}

    async def sweep(ids: list[UUID], stmt: Any) -> None:
        rows = (
            (
                await session.execute(
                    stmt,
                    {"block_ids": ids, "codes": list(_MAP_INDICES)},
                )
            )
            .mappings()
            .all()
        )
        for r in rows:
            bucket = out.setdefault(r["block_id"], {})
            bucket[r["index_code"]] = (float(r["mean"]), r["time"])

    await sweep(block_ids, _RECENT_STMT)

    stale = [bid for bid in block_ids if bid not in out]
    if stale:
        await sweep(stale, _UNBOUNDED_STMT)

    return out


@router.get(
    "/farms/{farm_id}/blocks/summary",
    response_model=BlocksSummaryResponse,
    summary="Map-experience block summary (health + indices + alerts) for a farm.",
)
async def get_blocks_summary(
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability("block.read", farm_id_param="farm_id")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> BlocksSummaryResponse:
    del context  # capability check side-effect is the only consumer

    # 2. Open-alert count + worst severity per block in this farm.
    alert_rows = (
        (
            await tenant_session.execute(
                text(
                    """
                    SELECT a.block_id,
                           count(*) FILTER (
                               WHERE a.severity IN ('warning', 'critical')
                           ) AS alert_count,
                           bool_or(a.severity = 'critical') AS has_critical,
                           bool_or(a.severity = 'warning')  AS has_warning
                    FROM alerts a
                    JOIN blocks b ON b.id = a.block_id
                    WHERE b.farm_id = :farm_id
                      AND a.status = 'open'
                    GROUP BY a.block_id
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        )
        .mappings()
        .all()
    )

    # 3. Current grid config per block, if any. `retired_at IS NULL` is the
    #    live row; 0054 gave configs valid time, so a rezoned block has an
    #    older superseded row alongside the current one and DISTINCT ON keeps
    #    the newest. A block can in principle be gridded against more than one
    #    product; the map colours by one index at a time, so the newest wins.
    grid_rows = (
        (
            await tenant_session.execute(
                text(
                    """
                    SELECT DISTINCT ON (g.block_id)
                           g.block_id,
                           g.product_id
                    FROM grid_configs g
                    JOIN blocks b ON b.id = g.block_id
                    WHERE b.farm_id = :farm_id
                      AND g.retired_at IS NULL
                      AND g.superseded_at IS NULL
                    ORDER BY g.block_id, g.created_at DESC
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        )
        .mappings()
        .all()
    )

    # 4. The full block-id roster — needed so blocks with no indices and
    #    no alerts still appear in the response (rendered as "unknown").
    block_ids = (
        (
            await tenant_session.execute(
                text(
                    """
                    SELECT id FROM blocks
                    WHERE farm_id = :farm_id
                      AND active_from <= current_date
                      AND (active_to IS NULL OR active_to > current_date)
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id},
            )
        )
        .scalars()
        .all()
    )

    # 1. Latest index value per (block, index). Recent window first, then
    #    an unbounded sweep for whichever blocks it found nothing for.
    idx_by_block = await _latest_indices(tenant_session, list(block_ids))

    # ---- Compose ---------------------------------------------------------

    alerts_by_block: dict[UUID, dict[str, Any]] = {}
    for r in alert_rows:
        sev: MapSeverity | None = (
            "critical" if r["has_critical"] else ("watch" if r["has_warning"] else None)
        )
        alerts_by_block[r["block_id"]] = {
            "alert_count": int(r["alert_count"] or 0),
            "alert_severity": sev,
        }

    grid_by_block: dict[UUID, UUID] = {r["block_id"]: r["product_id"] for r in grid_rows}

    units: list[BlockSummary] = []
    for bid in block_ids:
        idx = idx_by_block.get(bid, {})
        ndvi_pair = idx.get("ndvi")
        ndre_pair = idx.get("ndre")
        ndwi_pair = idx.get("ndwi")
        ndvi_current = ndvi_pair[0] if ndvi_pair else None
        ndre_current = ndre_pair[0] if ndre_pair else None
        ndwi_current = ndwi_pair[0] if ndwi_pair else None
        last_at = max(
            (p[1] for p in (ndvi_pair, ndre_pair, ndwi_pair) if p is not None),
            default=None,
        )

        a = alerts_by_block.get(bid, {})
        alert_count = int(a.get("alert_count", 0))
        alert_severity: MapSeverity | None = a.get("alert_severity")

        health = _classify_health(worst_alert_severity=alert_severity, ndvi_current=ndvi_current)

        units.append(
            BlockSummary(
                id=bid,
                health=health,
                alert_count=alert_count,
                alert_severity=alert_severity,
                ndvi_current=ndvi_current,
                ndre_current=ndre_current,
                ndwi_current=ndwi_current,
                grid_product_id=grid_by_block.get(bid),
                last_index_at=last_at,
            )
        )

    return BlocksSummaryResponse(
        farm_id=farm_id,
        as_of=datetime.now(UTC),
        units=units,
    )


def _classify_health(
    *, worst_alert_severity: MapSeverity | None, ndvi_current: float | None
) -> Health:
    if worst_alert_severity == "critical":
        return "critical"
    if worst_alert_severity == "watch":
        return "watch"
    if ndvi_current is None:
        return "unknown"
    if ndvi_current < 0.4:
        return "critical"
    if ndvi_current < 0.55:
        return "watch"
    return "healthy"
