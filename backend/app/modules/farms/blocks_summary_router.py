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
N blocks. Two SQL queries against the tenant schema, one in-process join.

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
from sqlalchemy import bindparam, text
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


class BlocksSummaryResponse(BaseModel):
    farm_id: UUID
    as_of: datetime
    units: list[BlockSummary]


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

    # 1. Latest index value per (block, index) for blocks in this farm.
    #    DISTINCT ON inside a CTE bounds the scan to currently-active
    #    blocks per the active_from/active_to lifecycle.
    index_rows = (
        (
            await tenant_session.execute(
                text(
                    """
                    WITH active_blocks AS (
                        SELECT id FROM blocks
                        WHERE farm_id = :farm_id
                          AND active_from <= current_date
                          AND (active_to IS NULL OR active_to > current_date)
                    )
                    SELECT DISTINCT ON (a.block_id, a.index_code)
                           a.block_id,
                           a.index_code,
                           a.mean,
                           a.time
                    FROM block_index_aggregates a
                    JOIN active_blocks b ON b.id = a.block_id
                    WHERE a.index_code = ANY(:codes)
                      AND a.mean IS NOT NULL
                    ORDER BY a.block_id, a.index_code, a.time DESC
                    """
                ).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True))),
                {"farm_id": farm_id, "codes": list(_MAP_INDICES)},
            )
        )
        .mappings()
        .all()
    )

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

    # 3. The full block-id roster — needed so blocks with no indices and
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

    # ---- Compose ---------------------------------------------------------

    # idx_by_block[block_id] = { 'ndvi': (mean, time), 'ndre': ..., 'ndwi': ... }
    idx_by_block: dict[UUID, dict[str, tuple[float, datetime]]] = {}
    for r in index_rows:
        bucket = idx_by_block.setdefault(r["block_id"], {})
        bucket[r["index_code"]] = (float(r["mean"]), r["time"])

    alerts_by_block: dict[UUID, dict[str, Any]] = {}
    for r in alert_rows:
        sev: MapSeverity | None = (
            "critical" if r["has_critical"] else ("watch" if r["has_warning"] else None)
        )
        alerts_by_block[r["block_id"]] = {
            "alert_count": int(r["alert_count"] or 0),
            "alert_severity": sev,
        }

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
