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

from app.shared.health_definition import AlertEvidence, HealthInputs, VerdictEvidence


@dataclass(frozen=True, slots=True)
class BlockEvidence:
    """One block's evidence, in the two shapes it is needed in.

    `inputs` goes to `resolve_health`. The counters beside it are for
    reporting: the resolver reads one alert per (severity, status, cell)
    group and does not care how many rows were in each group, but a
    reader looking at why a block is red does.

    The two disagree on purpose where a finding is made of cells. The
    counters see one finding; the resolver sees each cell, because that is
    what `cell_critical_share` compares against the block's grid.
    """

    inputs: HealthInputs
    alerts_by_severity: dict[str, int] = field(default_factory=dict)
    alerts_by_status: dict[str, int] = field(default_factory=dict)
    critical_cells: int = 0
    # The block's current crop, as the denormalised taxonomy path
    # (`mango`, `mango.keitt`). Not evidence about the block's condition —
    # it is what picks WHICH definition judges the evidence, per
    # `app.modules.health.service`. None when the block has no current
    # assignment, which resolves to the platform default.
    crop_path: str | None = None


# Counted alerts, in two kinds of row.
#
# The definition decides which statuses count, so SQL must not pre-filter to
# `open` the way the map's badge rollup does. Resolved rows are dropped here
# instead: `counted_statuses` refuses to include 'resolved' at parse time, so
# no definition can ever ask for them.
#
# **`kind` is what makes `cell_critical_share` able to fire at all.** A
# grouped alert is one finding stored as a parent plus one child per cell,
# and the parent carries `cell_id = NULL`. Filtering to findings — which the
# counters must do, or a 12-cell outbreak reads as 13 — therefore threw away
# every cell there was. Measured on prod 2026-09-03: of 542 unresolved rows,
# every single one with a `cell_id` was a child, and there were ZERO
# cell-scoped findings. So `critical_cells` was always 0 and the share could
# never be reached, whatever a farm set it to. Present, correct, and reaching
# nothing.
#
# So the statement returns both:
#
#   kind='finding'  one row per (severity, status) group, plus how many
#                   distinct cells that finding is made of. These feed the
#                   counters, and feed the resolver ONLY when they have no
#                   cells of their own.
#   kind='cell'     one row per distinct child cell, carrying the CHILD's own
#                   severity and status — "this cell is critical" is a fact
#                   about the cell, not about the card it hangs under.
#
# A finding with cells is not also emitted to the resolver as a block-scoped
# alert. It IS its cells; counting it both ways would force critical from the
# parent and make the share unreachable a second time.
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
    #
    # `status` and `when` are each one of two literals chosen by a bool
    # argument; the only caller-supplied values they carry are bound-parameter
    # placeholders. Hence the noqa on the closing quote — it cannot go on the
    # `return f"""` line, where it would land inside the string.
    sql = f"""
        WITH counted AS (
            SELECT a.id,
                   a.block_id,
                   a.severity,
                   {status} AS status,
                   a.cell_id,
                   a.group_parent_id
            FROM alerts a
            JOIN blocks b ON b.id = a.block_id
            WHERE b.farm_id = :farm_id
              {when}
        )
        -- Findings. A grouped alert is one finding stored as a parent plus
        -- one child per cell; counting both would read a 12-cell outbreak as
        -- 13 findings.
        SELECT 'finding' AS kind,
               f.block_id,
               f.severity,
               f.status,
               NULL::uuid AS cell_id,
               count(*) AS n,
               -- How many distinct cells this finding is actually made of.
               -- Zero means it is a statement about the whole block.
               coalesce(max(f.cells), 0) AS cells
        FROM (
            SELECT c.block_id,
                   c.severity,
                   c.status,
                   (
                       SELECT count(DISTINCT k.cell_id)
                       FROM counted k
                       WHERE k.group_parent_id = c.id
                         AND k.cell_id IS NOT NULL
                   ) AS cells
            FROM counted c
            WHERE c.group_parent_id IS NULL
        ) f
        GROUP BY f.block_id, f.severity, f.status
        UNION ALL
        -- The cells themselves, with their OWN severity and status.
        SELECT 'cell',
               c.block_id,
               c.severity,
               c.status,
               c.cell_id,
               count(*),
               0
        FROM counted c
        WHERE c.cell_id IS NOT NULL
        GROUP BY c.block_id, c.severity, c.status, c.cell_id
    """  # noqa: S608
    return sql


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


# The block's current decision-tree verdicts — the primary evidence.
#
# One row per open verdict: its status code, and the cell it is about when it
# is about a cell. The resolver ranks them and takes the worst, and counts the
# `alert` cells against the block's grid for `cell_critical_share`.
#
# This is a far better source for that share than the alert children it
# replaces. A tree writes a verdict for every cell it evaluates, whether or
# not anything fired, so the denominator and the numerator finally come from
# the same pass.
def _verdict_evidence_sql(*, as_of: bool) -> str:
    # `window` is one of two literals chosen by a bool argument, and the only
    # value it carries is a bound-parameter placeholder.
    window = (
        "v.valid_from <= :at AND (v.valid_to IS NULL OR v.valid_to > :at)"
        if as_of
        else "v.valid_to IS NULL"
    )
    sql = f"""
        SELECT v.block_id, v.status_code, v.cell_id,
               max(v.last_evaluated_at) AS last_evaluated_at
        FROM decision_tree_block_verdicts v
        WHERE v.farm_id = :farm_id AND {window}
        GROUP BY v.block_id, v.status_code, v.cell_id
    """
    return sql


_VERDICTS_NOW = text(_verdict_evidence_sql(as_of=False)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True))
)
_VERDICTS_AS_OF = text(_verdict_evidence_sql(as_of=True)).bindparams(
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


# The block's current crop path.
#
# `block_crops.crop_path` is denormalised in the tenant schema for exactly
# this kind of read — the decision-tree engine already uses it for targeting.
# Reading it here rather than joining the catalog keeps this module free of
# any dependency on how deep a crop's taxonomy goes.
#
# `is_current` and `deleted_at` together are what "the crop growing there
# now" means; a block carries its whole assignment history.
_CROP_PATHS = text(
    """
    SELECT bc.block_id, bc.crop_path
    FROM block_crops bc
    JOIN blocks b ON b.id = bc.block_id
    WHERE b.farm_id = :farm_id
      AND bc.is_current = TRUE
      AND bc.deleted_at IS NULL
      AND bc.crop_path IS NOT NULL
    """
).bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))


async def load_health_evidence(
    session: AsyncSession, *, farm_id: UUID, at: datetime | None = None
) -> dict[UUID, BlockEvidence]:
    """Every block's evidence for one farm, keyed by block id.

    Six statements, always the same six in the same order, whether or
    not `at` is given. A block with no evidence at all is simply absent
    from the result; callers must read that as "nothing looked", not as
    "nothing found" — `HealthInputs()` with every counter at zero
    resolves to unknown / no_coverage, which is the point.

    The crop path is NOT as-of. A block's crop assignment is what it is
    now; replaying which crop was growing on a past date would need an
    assignment timeline the tenant schema does not keep, and guessing
    would change which definition judged an old day's evidence.
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
    verdict_rows = await rows(_VERDICTS_AS_OF if at is not None else _VERDICTS_NOW)
    cell_rows = await rows(_CELL_COUNTS)
    crop_rows = await rows(_CROP_PATHS)

    alerts_by_block: dict[UUID, list[Any]] = {}
    for r in alert_rows:
        alerts_by_block.setdefault(r["block_id"], []).append(r)

    confidence_by_block: dict[UUID, Decimal] = {
        r["block_id"]: Decimal(str(r["max_confidence"]))
        for r in recommendation_rows
        if r["max_confidence"] is not None
    }
    traces_by_block = {r["block_id"]: r for r in trace_rows}
    verdicts_by_block: dict[UUID, list[Any]] = {}
    for r in verdict_rows:
        verdicts_by_block.setdefault(r["block_id"], []).append(r)
    cells_by_block = {r["block_id"]: int(r["total_cells"] or 0) for r in cell_rows}
    crop_by_block = {r["block_id"]: r["crop_path"] for r in crop_rows}

    block_ids = (
        set(alerts_by_block)
        | set(confidence_by_block)
        | set(traces_by_block)
        | set(verdicts_by_block)
        | set(cells_by_block)
        | set(crop_by_block)
    )
    return {
        bid: _compose(
            alert_groups=alerts_by_block.get(bid, []),
            max_recommendation_confidence=confidence_by_block.get(bid),
            traces=traces_by_block.get(bid),
            verdicts=verdicts_by_block.get(bid, []),
            total_cells=cells_by_block.get(bid, 0),
            crop_path=crop_by_block.get(bid),
        )
        for bid in block_ids
    }


def _compose(
    *,
    alert_groups: list[Any],
    max_recommendation_confidence: Decimal | None,
    traces: Any | None,
    total_cells: int,
    crop_path: str | None = None,
    verdicts: list[Any] | None = None,
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

        if g["kind"] == "finding":
            # The counters count findings, always. A 12-cell outbreak is one
            # thing that is wrong, whatever the resolver does with it below.
            by_severity[severity] = by_severity.get(severity, 0) + n
            by_status[status] = by_status.get(status, 0) + n
            # A finding made of cells IS its cells, and they are emitted as
            # their own rows. Passing the parent through as well would force
            # critical from a block-scoped alert and make the share
            # unreachable — the bug this shape exists to fix.
            if int(g["cells"] or 0) == 0:
                alerts.append(AlertEvidence(severity=severity, status=status, cell_id=None))
            continue

        # kind == "cell": one distinct cell of a grouped finding.
        if severity == "critical":
            critical_cells.add(cell_id)
        alerts.append(AlertEvidence(severity=severity, status=status, cell_id=cell_id))

    verdict_rows = verdicts or []
    verdict_evidence = tuple(
        VerdictEvidence(status_code=str(v["status_code"]), cell_id=v["cell_id"])
        for v in verdict_rows
    )
    verdict_seen = max(
        (v["last_evaluated_at"] for v in verdict_rows if v["last_evaluated_at"] is not None),
        default=None,
    )

    t = traces or {}
    return BlockEvidence(
        inputs=HealthInputs(
            alerts=tuple(alerts),
            verdicts=verdict_evidence,
            verdict_last_evaluated_at=verdict_seen,
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
        crop_path=crop_path,
    )


# What a block with no evidence at all resolves from. Callers hand this to
# `resolve_health` rather than skipping the block, so a block the sweep never
# reached gets the same treatment as one it reached and found nothing on:
# unknown, for the reason `no_coverage`.
EMPTY_EVIDENCE = BlockEvidence(inputs=HealthInputs())
