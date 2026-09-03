"""Loading one farm's health evidence from the tenant schema.

The queries behind `app.shared.health_definition`. That module decides;
this one fetches. Both callers of the health rule read through here, so
the map and the scorecard cannot answer from different evidence:

  * `farms/blocks_summary_router` — map polygons and the block dock
  * `insights/service.get_farm_health_summary` — the scorecard

That was not true before. The scorecard counted open, acknowledged and
snoozed alerts; the map counted open only, one alert at a time in a
per-block loop. One block could read Critical on the scorecard and
Healthy on the map on the same screen. Four farm-scoped statements
replace both, and neither caller assembles evidence of its own.

Raw SQL against tenant tables, no model imports: `app.shared` must not
depend on `app.modules`, and the tenant schema is already on the
session's `search_path` by the time any of this runs.

Everything takes an optional `at`. The map's date bar parks on a past
pass and the whole picture — alerts, recommendations, which sweep — has
to describe the farm as it stood then. Statuses are reconstructed rather
than read, because reading today's status would drop every finding that
has since been closed and make the past look calmer than it was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.health_definition import AlertEvidence, HealthInputs


@dataclass(frozen=True, slots=True)
class BlockEvidence:
    """One block's evidence, in the two shapes it is needed in.

    `inputs` goes to `resolve_health`. The counters beside it are for
    reporting: the resolver reads one alert per (severity, status, cell)
    group and does not care how many rows were in each group, but a
    reader looking at why a block is red does.
    """

    inputs: HealthInputs
    alerts_by_severity: dict[str, int] = field(default_factory=dict)
    alerts_by_status: dict[str, int] = field(default_factory=dict)
    critical_cells: int = 0


# Counted alerts, one row per (severity, status, cell) group.
#
# The definition decides which statuses count, so SQL must not pre-filter to
# `open` the way the map's badge rollup does. Resolved rows are dropped here
# instead: `counted_statuses` refuses to include 'resolved' at parse time, so
# no definition can ever ask for them.
#
# Grouping rather than returning raw rows is lossless for the resolver. It
# reads severity and status to pick a class — the same answer for every row
# in a group — and collects cell ids into a set for the share test. `n`
# carries the real count back for the two counters.
def _alert_evidence_sql(*, as_of: bool) -> str:
    if as_of:
        # Status has to be reconstructed, not read. The stored value is
        # today's; an alert that has since been resolved was still open then.
        #
        # `acknowledged_at` replays exactly. `snoozed` does not: the table
        # keeps `snoozed_until` and no `snoozed_at`, so there is no instant to
        # compare against and an as-of read reports a snoozed alert as open.
        # Under the default definition both count, and they differ only when
        # `snoozed_as` is set — so the loss is bounded and visible here rather
        # than guessed at.
        when = """AND a.created_at <= :at
                  AND (a.resolved_at IS NULL OR a.resolved_at > :at)"""
        status = """CASE
                       WHEN a.acknowledged_at IS NOT NULL
                            AND a.acknowledged_at <= :at THEN 'acknowledged'
                       ELSE 'open'
                   END"""
    else:
        when = "AND a.status <> 'resolved'"
        status = "a.status"
    # Grouped in an outer query rather than by repeating the CASE in a
    # GROUP BY: the reconstructed status is an expression, and naming it once
    # is what keeps the two branches the same shape.
    return f"""
        SELECT e.block_id,
               e.severity,
               e.status,
               e.cell_id,
               count(*) AS n
        FROM (
            SELECT a.block_id,
                   a.severity,
                   {status} AS status,
                   a.cell_id
            FROM alerts a
            JOIN blocks b ON b.id = a.block_id
            WHERE b.farm_id = :farm_id
              {when}
              -- Findings, not rows. A grouped alert is one finding stored as
              -- a parent plus one child per cell; counting both would read a
              -- 12-cell outbreak as 13 findings.
              AND a.group_parent_id IS NULL
        ) e
        GROUP BY e.block_id, e.severity, e.status, e.cell_id
    """


_ALERT_EVIDENCE_NOW = text(_alert_evidence_sql(as_of=False)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True))
)
# `at` is bound as a real datetime, never a string: asyncpg infers nothing
# from a bare text() placeholder, and a string reaching a timestamptz
# comparison is the shape that has raised DataError in prod before.
_ALERT_EVIDENCE_AS_OF = text(_alert_evidence_sql(as_of=True)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
    bindparam("at", type_=DateTime(timezone=True)),
)


# Highest confidence among the block's open recommendations.
#
# `recommendations` carries `farm_id` directly, so this needs no join.
# Alert leaves are pinned to 1.0 by `recommendations/engine.py`; only
# recommendation leaves carry a real 0-to-1 number, which is why the
# platform default leaves `recommendation_floor` unset and this value
# moves nothing today.
def _recommendation_floor_sql(*, as_of: bool) -> str:
    when = (
        """
                      AND r.created_at <= :at
                      AND (r.applied_at IS NULL OR r.applied_at > :at)
                      AND (r.dismissed_at IS NULL OR r.dismissed_at > :at)
        """
        if as_of
        else """
                      AND r.state = 'open'
        """
    )
    return f"""
        SELECT r.block_id,
               max(r.confidence) AS max_confidence
        FROM recommendations r
        WHERE r.farm_id = :farm_id
          {when}
          AND r.group_parent_id IS NULL
        GROUP BY r.block_id
    """


_RECOMMENDATION_FLOOR_NOW = text(_recommendation_floor_sql(as_of=False)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True))
)
_RECOMMENDATION_FLOOR_AS_OF = text(_recommendation_floor_sql(as_of=True)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
    bindparam("at", type_=DateTime(timezone=True)),
)


# Trace counts per block from the newest sweep.
#
# `kind = 'sweep'` and not simply the newest run: an `on_demand` run covers
# the one block somebody pressed Evaluate on, and taking it would report zero
# traces for every other block in the farm — turning the whole map unknown
# because one person opened one block.
#
# A failed sweep is still taken. Its missing blocks then read `no_coverage`,
# which is the honest answer: the run did not reach them. Skipping it and
# falling back to an older sweep would present stale verdicts as fresh ones.
#
# The run is chosen in a CTE so this stays one statement. The join is on
# `run_id`, which `ix_decision_tree_eval_traces_run` covers; `farm_id` has no
# index on that table, and inside a single run it is a filter over a bounded
# set rather than a scan of the whole history.
def _trace_counts_sql(*, as_of: bool) -> str:
    when = "AND r.started_at <= :at" if as_of else ""
    # `when` is one of two literals chosen by a bool argument, and the only
    # value it ever carries is a bound-parameter placeholder. Nothing a caller
    # sends reaches the SQL text — hence the noqa on the closing quote.
    sql = f"""
        WITH newest AS (
            SELECT r.id
            FROM decision_tree_eval_runs r
            WHERE r.kind = 'sweep'
              {when}
            ORDER BY r.started_at DESC, r.id DESC
            LIMIT 1
        )
        SELECT t.block_id,
               count(*) FILTER (WHERE t.status = 'fired')   AS traces_fired,
               count(*) FILTER (WHERE t.status = 'clear')   AS traces_clear,
               count(*) FILTER (WHERE t.status = 'skipped') AS traces_skipped,
               count(*) FILTER (WHERE t.status = 'error')   AS traces_error,
               max(t.evaluated_at) AS last_evaluated_at
        FROM decision_tree_eval_traces t
        JOIN newest n ON n.id = t.run_id
        WHERE t.farm_id = :farm_id
        GROUP BY t.block_id
    """  # noqa: S608
    return sql


_TRACE_COUNTS_NOW = text(_trace_counts_sql(as_of=False)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True))
)
_TRACE_COUNTS_AS_OF = text(_trace_counts_sql(as_of=True)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
    bindparam("at", type_=DateTime(timezone=True)),
)


# Cell count of the block's live grid — the denominator for
# `cell_critical_share`.
#
# `DISTINCT ON (block_id) ... ORDER BY created_at DESC` picks the newest live
# config, which is the same choice the map makes for `grid_product_id`. A
# block can in principle be zoned against more than one product; summing the
# cells of both would inflate the denominator and quietly stop a real
# outbreak from reaching the share.
#
# 0054 gave configs valid time, so a rezoned block also holds superseded rows.
# Counting those too would measure today's criticals against a grid that no
# longer exists.
_CELL_COUNTS = text(
    """
    SELECT live.block_id,
           (SELECT count(*) FROM grid_cells c WHERE c.grid_config_id = live.id)
               AS total_cells
    FROM (
        SELECT DISTINCT ON (g.block_id) g.block_id, g.id
        FROM grid_configs g
        JOIN blocks b ON b.id = g.block_id
        WHERE b.farm_id = :farm_id
          AND g.retired_at IS NULL
          AND g.superseded_at IS NULL
        ORDER BY g.block_id, g.created_at DESC
    ) live
    """
).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))


async def load_health_evidence(
    session: AsyncSession, *, farm_id: UUID, at: datetime | None = None
) -> dict[UUID, BlockEvidence]:
    """Every block's evidence for one farm, keyed by block id.

    Four statements, always the same four in the same order, whether or
    not `at` is given. A block with no evidence at all is simply absent
    from the result; callers must read that as "nothing looked", not as
    "nothing found" — `HealthInputs()` with every counter at zero
    resolves to unknown / no_coverage, which is the point.
    """
    params: dict[str, Any] = {"farm_id": farm_id}
    if at is not None:
        params["at"] = at

    async def rows(stmt: Any) -> list[Any]:
        return list((await session.execute(stmt, params)).mappings().all())

    alert_rows = await rows(_ALERT_EVIDENCE_AS_OF if at is not None else _ALERT_EVIDENCE_NOW)
    recommendation_rows = await rows(
        _RECOMMENDATION_FLOOR_AS_OF if at is not None else _RECOMMENDATION_FLOOR_NOW
    )
    trace_rows = await rows(_TRACE_COUNTS_AS_OF if at is not None else _TRACE_COUNTS_NOW)
    cell_rows = await rows(_CELL_COUNTS)

    alerts_by_block: dict[UUID, list[Any]] = {}
    for r in alert_rows:
        alerts_by_block.setdefault(r["block_id"], []).append(r)

    confidence_by_block: dict[UUID, Decimal] = {
        r["block_id"]: Decimal(str(r["max_confidence"]))
        for r in recommendation_rows
        if r["max_confidence"] is not None
    }
    traces_by_block = {r["block_id"]: r for r in trace_rows}
    cells_by_block = {r["block_id"]: int(r["total_cells"] or 0) for r in cell_rows}

    block_ids = (
        set(alerts_by_block) | set(confidence_by_block) | set(traces_by_block) | set(cells_by_block)
    )
    return {
        bid: _compose(
            alert_groups=alerts_by_block.get(bid, []),
            max_recommendation_confidence=confidence_by_block.get(bid),
            traces=traces_by_block.get(bid),
            total_cells=cells_by_block.get(bid, 0),
        )
        for bid in block_ids
    }


def _compose(
    *,
    alert_groups: list[Any],
    max_recommendation_confidence: Decimal | None,
    traces: Any | None,
    total_cells: int,
) -> BlockEvidence:
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    critical_cells: set[Any] = set()
    alerts: list[AlertEvidence] = []

    for g in alert_groups:
        severity = str(g["severity"])
        status = str(g["status"])
        n = int(g["n"] or 0)
        cell_id = g["cell_id"]
        by_severity[severity] = by_severity.get(severity, 0) + n
        by_status[status] = by_status.get(status, 0) + n
        if severity == "critical" and cell_id is not None:
            critical_cells.add(cell_id)
        alerts.append(AlertEvidence(severity=severity, status=status, cell_id=cell_id))

    t = traces or {}
    return BlockEvidence(
        inputs=HealthInputs(
            alerts=tuple(alerts),
            total_cells=total_cells,
            max_recommendation_confidence=max_recommendation_confidence,
            traces_fired=int(t.get("traces_fired") or 0),
            traces_clear=int(t.get("traces_clear") or 0),
            traces_skipped=int(t.get("traces_skipped") or 0),
            traces_error=int(t.get("traces_error") or 0),
            last_evaluated_at=t.get("last_evaluated_at"),
        ),
        alerts_by_severity=by_severity,
        alerts_by_status=by_status,
        critical_cells=len(critical_cells),
    )


# What a block with no evidence at all resolves from. Callers hand this to
# `resolve_health` rather than skipping the block, so a block the sweep never
# reached gets the same treatment as one it reached and found nothing on:
# unknown, for the reason `no_coverage`.
EMPTY_EVIDENCE = BlockEvidence(inputs=HealthInputs())
