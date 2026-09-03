"""Map-experience block summary endpoint.

Single call returns one row per active block in a farm with the data the
map-first frontend needs to color polygons + show alert badges:

  GET /api/v1/farms/{farm_id}/blocks/summary

  → { farm_id, as_of, units: [{
        id, health, alert_count, alert_severity, alert_action_type,
        ndvi_current, ndre_current, ndwi_current,
        last_index_at,
      }, ...] }

Designed to replace ~Nx4 round-trips (per-block detail + per-block-per-
index timeseries + tenant-wide alert list) the prototype was making for
N blocks. Three SQL queries against the tenant schema (alerts, the block
roster, and the latest index values), plus a fourth only when a block has
no reading inside the recent window — see `_RECENT_WINDOW_DAYS`.

Health classification is NOT decided here. The one rule lives in
`app.shared.health.classify_health`; this module only gathers its
inputs and calls it. It used to carry a private copy of the rule, which
drifted from the shared one and from the frontend's third copy.

Each unit also carries `health_evidence`: the inputs the bounded health
definition reads (`app.shared.health_definition`), plus the class that
definition WOULD give the block. That preview is reported and not
applied — `health` is still the NDVI rule. Shipping the evidence one
step ahead of the switch is what makes the switch checkable: the two
answers can be compared on a real farm before either page changes.

Caching: deferred. The prototype exercises this from the polling loop
(60s interval); add Redis with a 60s TTL when the validation cohort
grows past a single tester.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.auth.context import RequestContext
from app.shared.db.session import get_db_session
from app.shared.health import Health, classify_health
from app.shared.health_definition import (
    PLATFORM_DEFAULT_DEFINITION,
    AlertEvidence,
    HealthInputs,
    HealthReason,
    resolve_health,
)
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["farms"])


# Indices this FARM-WIDE summary carries, one column each, for every block on
# the map at once.
#
# It is three of thirteen on purpose — the response colours polygons and fills
# the units rail, and a fourteen-column row per block is a cost paid on every
# 60s poll. It is NOT a statement about what the pipeline computes: the ingest
# task writes a `block_index_aggregates` row per index, and
# `/blocks/{id}/indices/{code}/timeseries` serves any of them.
#
# ⚠️ That distinction was lost once already. This tuple's old comment said
# "backend has no NDMI", the frontend copied the claim, and the Block Dock
# spent a year showing ten of its thirteen index tiles disabled and labelled
# "Grid only". Widen this tuple only for the map's own needs; a block-level
# reading does not have to come through here.
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

# `Health` comes from app.shared.health — the single source for the rule
# and its vocabulary. `MapSeverity` is the non-null half of the shared
# `AlertSeverityBucket`: the response field is nullable, so the schema
# spells the None out itself.
MapSeverity = Literal["watch", "critical"]


class HealthEvidence(BaseModel):
    """What the bounded health definition reads about one block.

    Reported, never applied. `BlockSummary.health` is still the NDVI rule
    in `app.shared.health`. `preview_health` is what
    `app.shared.health_definition.resolve_health` gives the same block
    under the platform default definition, so the two can be compared on
    a real farm before anything is switched over.

    The alert counters here do NOT match `BlockSummary.alert_count`, and
    that is the point. `alert_count` is open, warning-or-critical only.
    These count every alert the definition may count — open, acknowledged
    and snoozed — at every severity including `info`. A block can show
    `alert_count: 0` and a non-empty `alerts_by_status` when its only
    alert has been acknowledged and not fixed.
    """

    model_config = ConfigDict(from_attributes=True)

    # Counted alerts (see the class docstring for what "counted" means),
    # bucketed two ways. Both count findings, not rows: grouped children
    # are excluded the same way `alert_count` excludes them.
    alerts_by_severity: dict[str, int]
    alerts_by_status: dict[str, int]
    # Distinct grid cells carrying a critical alert, and how many cells the
    # block has. `cell_critical_share` compares these two; until a definition
    # sets that share, one critical cell is enough to make the block critical.
    critical_cells: int
    total_cells: int
    # Highest confidence among the block's open recommendations, or null.
    # Alert leaves are pinned to 1.0 by the engine, so this is only ever
    # informative for recommendation leaves.
    max_recommendation_confidence: float | None
    # Per-status trace counts from the newest sweep, for THIS block. All
    # four zero means the sweep never reached the block, which is why
    # "no open alert" cannot be read as health on its own.
    traces_fired: int
    traces_clear: int
    traces_skipped: int
    traces_error: int
    last_evaluated_at: datetime | None
    preview_health: Health
    preview_reason: HealthReason


class BlockSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    health: Health
    alert_count: int
    alert_severity: MapSeverity | None
    # The verb the worst open alert's decision-tree leaf chose — one of the
    # `recommendations.action_type` values (migration 0015), carried on the
    # alert row since 0063. The map picks the marker's glyph from it, so a
    # water-stress alert and a pest alert stop looking like the same dot.
    # Null when the block has no open alert, or when the leaf named no verb.
    alert_action_type: str | None = None
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
    # The inputs to the health definition, and the class it would give.
    # Additive: nothing renders it yet.
    health_evidence: HealthEvidence


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


# Open-alert rollup per block, in two shapes.
#
# The two differ only in what "open" means. `_ALERT_ROLLUP_NOW` reads the
# stored `status`, which is what the map has always done. `_ALERT_ROLLUP_AS_OF`
# reconstructs it for a past instant: raised by then, and not resolved until
# after then.
#
# Reconstructing rather than trusting `status` is the whole point. An alert
# raised three weeks ago and closed last Tuesday IS part of the picture of a
# pass from a month ago, and `status = 'open'` would drop it — so scrubbing
# further back would show fewer and fewer alerts, which reads as "the farm was
# fine then" when the opposite is true.
#
# `acknowledged` and `snoozed` rows are counted the same way `status = 'open'`
# never did: an alert is either raised-and-unresolved or it is not. That
# widens the as-of count slightly against the live one, and the alternative —
# replaying an acknowledgement timeline the table does not keep — is not
# available.
def _alert_rollup_sql(*, as_of: bool) -> str:
    when = (
        """
                      AND a.created_at <= :at
                      AND (a.resolved_at IS NULL OR a.resolved_at > :at)
        """
        if as_of
        else """
                      AND a.status = 'open'
        """
    )
    return f"""
        SELECT a.block_id,
               count(*) FILTER (
                   WHERE a.severity IN ('warning', 'critical')
               ) AS alert_count,
               bool_or(a.severity = 'critical') AS has_critical,
               bool_or(a.severity = 'warning')  AS has_warning,
               -- The verb of the WORST, then NEWEST, open alert.
               -- The map draws one glyph per block, so it has to
               -- pick one of a mixed bag; picking the worst one
               -- matches what the badge's colour already says,
               -- and the count beside it says there are others.
               -- NULLs are filtered rather than ordered last so
               -- a block whose worst alert names no verb still
               -- shows the verb of the next one down instead of
               -- falling back to the neutral glyph.
               (array_agg(a.action_type ORDER BY
                   CASE a.severity
                       WHEN 'critical' THEN 0
                       WHEN 'warning' THEN 1
                       ELSE 2
                   END,
                   a.created_at DESC
               ) FILTER (WHERE a.action_type IS NOT NULL))[1]
                   AS alert_action_type
        FROM alerts a
        JOIN blocks b ON b.id = a.block_id
        WHERE b.farm_id = :farm_id
          {when}
          -- Findings, not rows. A grouped alert is one finding
          -- stored as a parent plus one child per cell; counting
          -- both would badge a 12-cell outbreak as 13 alerts.
          AND a.group_parent_id IS NULL
        GROUP BY a.block_id
    """


_ALERT_ROLLUP_NOW = text(_alert_rollup_sql(as_of=False)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True))
)
# `at` is bound as a real datetime, never a string: asyncpg infers nothing
# from a bare text() placeholder, and a string reaching a timestamptz
# comparison is the shape that has raised DataError in prod before.
_ALERT_ROLLUP_AS_OF = text(_alert_rollup_sql(as_of=True)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True)),
    bindparam("at", type_=DateTime(timezone=True)),
)


# ---------------------------------------------------------------------------
# Health-definition evidence.
#
# Three more reads, all farm-scoped and all optional to the shipped answer:
# they fill `health_evidence`, and nothing decides a block's class from them
# yet. They are separate statements rather than extra columns on the rollup
# above because the rollup answers a different question — the map badge —
# and widening it would change what the badge counts.
#
# Cost: three round trips on a request the console polls every 60s. That is
# the same bet the module docstring already records about caching; revisit
# both together when the cohort grows.
# ---------------------------------------------------------------------------


# Counted alerts, one row per (severity, status, cell) group.
#
# The definition decides which statuses count, so SQL must not pre-filter to
# `open` the way the badge rollup does. Resolved rows are dropped here
# instead: `counted_statuses` refuses to include 'resolved' at parse time, so
# no definition can ever ask for them.
#
# Grouping rather than returning raw rows is lossless for the resolver. It
# reads severity and status to pick a class — idempotent across duplicates —
# and collects cell ids into a set for the share test. `n` carries the real
# count back for the response's two counters.
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
              -- Findings, not rows — same reason as the badge rollup.
              AND a.group_parent_id IS NULL
        ) e
        GROUP BY e.block_id, e.severity, e.status, e.cell_id
    """


_ALERT_EVIDENCE_NOW = text(_alert_evidence_sql(as_of=False)).bindparams(
    bindparam("farm_id", type_=PG_UUID(as_uuid=True))
)
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


@router.get(
    "/farms/{farm_id}/blocks/summary",
    response_model=BlocksSummaryResponse,
    summary="Map-experience block summary (health + indices + alerts) for a farm.",
)
async def get_blocks_summary(
    farm_id: UUID,
    # `Annotated`, not `at: ... = Query(None)`. With the old form the default
    # IS the `Query` sentinel object, so calling this function directly — which
    # every unit test in tests/unit/modules/farms does — hands `at` a truthy
    # non-datetime and takes the as-of branch by accident. Annotated keeps the
    # default a real `None`.
    at: Annotated[
        datetime | None,
        Query(
            description=(
                "Answer the alert rollup as of this instant instead of now. "
                "Only alerts raised on or before it, and still unresolved "
                "then, are counted. Omitted means now."
            ),
        ),
    ] = None,
    context: RequestContext = Depends(requires_capability("block.read", farm_id_param="farm_id")),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> BlocksSummaryResponse:
    del context  # capability check side-effect is the only consumer

    # The map is a picture of one day. When the console's date bar is parked
    # on a past pass it sends that day, and the chips have to describe the
    # farm as it stood then — an alert that opened this morning did not exist
    # on a scene from last week, and drawing it there makes the map disagree
    # with its own date.
    #
    # "Open as of T" is two conditions, not one: raised by T, and not resolved
    # until after T. Reading `status = 'open'` alone would drop every alert
    # that has since been closed, so scrubbing back would show FEWER alerts
    # the further back you went — the opposite of the truth.
    as_of_alerts = _ALERT_ROLLUP_AS_OF if at is not None else _ALERT_ROLLUP_NOW

    # 2. Open-alert count + worst severity per block in this farm.
    alert_rows = (
        (
            await tenant_session.execute(
                as_of_alerts,
                {"farm_id": farm_id, "at": at} if at is not None else {"farm_id": farm_id},
            )
        )
        .mappings()
        .all()
    )

    # 2b. Health-definition evidence: counted alerts, open recommendations,
    #     and the newest sweep's traces. Nothing here decides `health`; it
    #     fills `health_evidence` so the new rule can be compared against the
    #     shipped one on a real farm. All three take the same `at`.
    params = {"farm_id": farm_id, "at": at} if at is not None else {"farm_id": farm_id}

    evidence_rows = (
        (
            await tenant_session.execute(
                _ALERT_EVIDENCE_AS_OF if at is not None else _ALERT_EVIDENCE_NOW, params
            )
        )
        .mappings()
        .all()
    )
    recommendation_rows = (
        (
            await tenant_session.execute(
                _RECOMMENDATION_FLOOR_AS_OF if at is not None else _RECOMMENDATION_FLOOR_NOW,
                params,
            )
        )
        .mappings()
        .all()
    )
    trace_rows = (
        (
            await tenant_session.execute(
                _TRACE_COUNTS_AS_OF if at is not None else _TRACE_COUNTS_NOW, params
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
                           g.product_id,
                           -- Denominator for `cell_critical_share`. Counted
                           -- from the live config only, so a rezoned block
                           -- is measured against the grid it has now and not
                           -- against the retired one's cells as well.
                           (
                               SELECT count(*)
                               FROM grid_cells c
                               WHERE c.grid_config_id = g.id
                           ) AS total_cells
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
            "alert_action_type": r["alert_action_type"],
        }

    grid_by_block: dict[UUID, UUID] = {r["block_id"]: r["product_id"] for r in grid_rows}
    cells_by_block: dict[UUID, int] = {r["block_id"]: int(r["total_cells"] or 0) for r in grid_rows}

    evidence_by_block: dict[UUID, list[dict[str, Any]]] = {}
    for r in evidence_rows:
        evidence_by_block.setdefault(r["block_id"], []).append(dict(r))

    recommendation_by_block: dict[UUID, Decimal] = {
        r["block_id"]: Decimal(str(r["max_confidence"]))
        for r in recommendation_rows
        if r["max_confidence"] is not None
    }

    traces_by_block: dict[UUID, dict[str, Any]] = {r["block_id"]: dict(r) for r in trace_rows}

    # One instant for every block in the response, so two blocks cannot be
    # judged stale against clocks a few milliseconds apart. A caller may send
    # `at` with no offset; the resolver subtracts it from a timestamp that has
    # one, so it is stamped UTC here. `as_of` in the response is left exactly
    # as it was — this normalisation is the resolver's, not the echo's.
    resolver_now = at if at is not None else datetime.now(UTC)
    if resolver_now.tzinfo is None:
        resolver_now = resolver_now.replace(tzinfo=UTC)

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
        alert_action_type: str | None = a.get("alert_action_type")

        health = classify_health(worst_alert_severity=alert_severity, ndvi_current=ndvi_current)

        evidence = _health_evidence(
            alert_groups=evidence_by_block.get(bid, []),
            total_cells=cells_by_block.get(bid, 0),
            max_recommendation_confidence=recommendation_by_block.get(bid),
            traces=traces_by_block.get(bid),
            now=resolver_now,
        )

        units.append(
            BlockSummary(
                id=bid,
                health=health,
                alert_count=alert_count,
                alert_severity=alert_severity,
                alert_action_type=alert_action_type,
                ndvi_current=ndvi_current,
                ndre_current=ndre_current,
                ndwi_current=ndwi_current,
                grid_product_id=grid_by_block.get(bid),
                health_evidence=evidence,
                last_index_at=last_at,
            )
        )

    return BlocksSummaryResponse(
        farm_id=farm_id,
        # Echoes the instant the answer describes, so a caller can tell an
        # as-of response from a live one without re-reading its own request.
        as_of=at or datetime.now(UTC),
        units=units,
    )


def _health_evidence(
    *,
    alert_groups: list[dict[str, Any]],
    total_cells: int,
    max_recommendation_confidence: Decimal | None,
    traces: dict[str, Any] | None,
    now: datetime,
) -> HealthEvidence:
    """Turn one block's raw evidence rows into the reported shape.

    Builds the same `HealthInputs` the resolver will read in Phase 4 and
    runs it, so `preview_health` cannot drift from what the switch will
    actually do: there is one construction of the inputs, not one for the
    preview and another for the real answer.
    """
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
        # One evidence object per group, not per row. The resolver reads
        # severity and status to pick a class, which is the same answer for
        # every row in a group, and collects cell ids into a set.
        alerts.append(AlertEvidence(severity=severity, status=status, cell_id=cell_id))

    t = traces or {}
    inputs = HealthInputs(
        alerts=tuple(alerts),
        total_cells=total_cells,
        max_recommendation_confidence=max_recommendation_confidence,
        traces_fired=int(t.get("traces_fired") or 0),
        traces_clear=int(t.get("traces_clear") or 0),
        traces_skipped=int(t.get("traces_skipped") or 0),
        traces_error=int(t.get("traces_error") or 0),
        last_evaluated_at=t.get("last_evaluated_at"),
    )
    preview_health, preview_reason = resolve_health(PLATFORM_DEFAULT_DEFINITION, inputs, now=now)

    return HealthEvidence(
        alerts_by_severity=by_severity,
        alerts_by_status=by_status,
        critical_cells=len(critical_cells),
        total_cells=total_cells,
        max_recommendation_confidence=(
            float(max_recommendation_confidence)
            if max_recommendation_confidence is not None
            else None
        ),
        traces_fired=inputs.traces_fired,
        traces_clear=inputs.traces_clear,
        traces_skipped=inputs.traces_skipped,
        traces_error=inputs.traces_error,
        last_evaluated_at=inputs.last_evaluated_at,
        preview_health=preview_health,
        preview_reason=preview_reason,
    )
