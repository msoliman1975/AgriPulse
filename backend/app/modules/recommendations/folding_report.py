"""The estate dry run and its report (design section 9, stage B).

A beta (folding) tree is read before it is switched on for a tenant. Reading it
means running it over every active block the tenant has — and over every cell,
when the tree is cell-scoped — and counting what came out. Four questions, and
the whole module exists to answer them with numbers:

1. **Which finding sets does this tree produce, and how often?** One row per
   set, sorted by count, each saying whether a combination rule matched it or
   the fold composed the text from the catalogue clauses.
2. **Which rules never fire?** A rule that fires on no cell in the tenant is
   either wrong or unreachable, and the author has to see that before a card
   built on it reaches a farmer.
3. **How often does the fold compose?** Matching is exact (design decision 7),
   so a third finding sends the fold to composition. Composition is the main
   path, not a fallback. A composed share near 100 percent says the rules are
   not earning their place.
4. **How many cells error?** A switch on a missing index stops the walk, and
   cloud cover makes a missing index common. This number says whether cloud
   cover will blank a block before any tenant is switched on, which is why it
   is the headline of the report and not a footnote.

**Nothing here writes a card.** The unit of work is
``FoldingTreeAuthorService.dry_run``, which folds one block cell by cell and
writes nothing at all — no recommendation, no alert, no evaluation trace. This
module does not change that and must never change it. The one row it does
write is its own report row (tenant migration 0096), which is the record that
the run happened.

**Timing.** ``total_ms`` is wall-clock for the whole run, and ``per_cell_ms``
divides it by the cells evaluated. Both include the per-block data loads —
imagery aggregates, weather, signals, grid — because the sweep pays those too,
and a walk-only figure would understate sweep cost by the part that dominates
it. The per-block table shows where the time went.

**Per-node timing is not here, and that is a gap, not an oversight.**
``folding_engine.walk_tree`` has no timing hook and
``folding_authoring._fold_one_cell`` drops ``walk.path`` before returning, so
no caller outside those two modules can see which node a walk spent its time
in. Both modules belong to other sessions and this one does not edit them. The
report carries ``node_timing.available = false`` and the reason, rather than a
number that was guessed.

Design: docs/proposals/unified-decision-tree-engine.md sections 9 and 10.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.recommendations.folding_compiler import kind_of_node
from app.modules.recommendations.folding_engine import CombinationRule

_log = get_logger(__name__)

# How many finding-set rows the stored report keeps in full. The rest are
# rolled into one "other sets" line, the way section 9's report prints it. The
# cap exists because the number of distinct sets is bounded only by the number
# of registered codes: a tree registering 10 codes can in principle produce
# 1,023 sets, and a report row is read whole.
TOP_SETS: int = 50

# `node 'x'` covers every error the walk raises; `node id 'x'` covers the
# unknown-node case. The first match is taken, which for
# "cycle: node 'a' leads back to 'b'" names 'a' — the node holding the edge
# that closes the cycle, which is the node an author has to edit.
_NODE_IN_ERROR = re.compile(r"node(?: id)? '([^']+)'")


def error_node_id(message: str | None) -> str | None:
    """The node id named in a walk error, or None.

    Parsed from the message because the fold's per-cell row carries the error
    text and not the node: ``_fold_one_cell`` returns ``stopped_at``, which is
    None precisely when there is an error. One line in that function
    (returning the last path step's node id) would remove this regular
    expression; the function belongs to another session, so the parse stays
    here and the pull request says so.
    """
    if not message:
        return None
    found = _NODE_IN_ERROR.search(message)
    return found.group(1) if found is not None else None


def rule_label(rule: CombinationRule) -> str:
    """What the report calls one combination rule.

    The author's own id when the rule has one, because that is what they read
    in the designer. Otherwise the set itself, which is unambiguous: two rules
    cannot hold the same set and both fire, since matching is on equality.

    In practice the set is always what is used. ``folding_compiler``'s
    ``_check_combinations`` keeps codes, action_type, status and both texts,
    and drops ``code``, so no author-given rule id survives a publish. Design
    section 9 prints "rule r3", which needs that id kept; that is a gap in the
    compiler, and the compiler belongs to another session.
    """
    if rule.code:
        return rule.code
    return set_label(sorted(rule.codes))


def set_label(codes: Sequence[str]) -> str:
    """``{dry, ndvi_low}`` — the report's name for one finding set."""
    if not codes:
        return "{}"
    return "{" + ", ".join(codes) + "}"


def _pct(part: int, whole: int) -> float:
    """A percentage to one decimal place, and 0.0 rather than a divide by zero."""
    if whole <= 0:
        return 0.0
    return round(part * 100.0 / whole, 1)


@dataclass(frozen=True, slots=True)
class BlockFold:
    """One block's dry run, as the estate run collected it.

    ``targeted`` is the tree's own targeting verdict for this block. A block
    the tree does not target is folded anyway — the per-block dry run reports
    targeting rather than enforcing it — but its cells are counted separately
    and kept out of every total, because the sweep would never walk them and
    counting them would overstate what the tree does.
    """

    block_id: UUID
    block_name: str | None
    farm_id: UUID | None
    farm_name: str | None
    targeted: bool
    duration_ms: float
    cells: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None
    #: How many of this block's cells walked through each node.
    node_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _SetTally:
    """Running counts for one finding set."""

    codes: tuple[str, ...]
    count: int = 0
    composed: int = 0
    matched_rule: str | None = None
    status: str | None = None
    severity: str | None = None
    action_type: str | None = None
    text_en: str | None = None
    blocks: set[UUID] = field(default_factory=set)


def build_estate_report(  # noqa: PLR0915 - one pass over the cells, counting six things
    *,
    blocks: Sequence[BlockFold],
    rules: Sequence[CombinationRule],
    scope: str,
    total_ms: float,
    top_sets: int = TOP_SETS,
    nodes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn one run's per-block folds into the report of section 9.

    Pure: no session, no clock, no configuration. Everything it reports is
    derived from ``blocks`` and ``rules``, so the unit tests feed it fixtures
    and read the numbers back.
    """
    counted = [b for b in blocks if b.targeted and b.error is None]
    coverage: Counter[str] = Counter()
    for block in blocks:
        if block.targeted and block.error is None:
            coverage.update(block.node_counts)
    not_targeted = [b for b in blocks if not b.targeted]
    failed = [b for b in blocks if b.error is not None]

    tallies: dict[tuple[str, ...], _SetTally] = {}
    errors: Counter[str] = Counter()
    error_examples: dict[str, str] = {}
    cells_evaluated = 0
    cells_errored = 0
    cells_healthy = 0
    cells_carded = 0
    cells_composed = 0

    for block in counted:
        for cell in block.cells:
            cells_evaluated += 1
            error = cell.get("error")
            if error:
                cells_errored += 1
                node = error_node_id(str(error)) or "(no node named)"
                errors[node] += 1
                error_examples.setdefault(node, str(error))
                continue
            identity = tuple(cell.get("identity") or ())
            if not identity:
                cells_healthy += 1
                continue
            cells_carded += 1
            composed = bool(cell.get("composed"))
            if composed:
                cells_composed += 1
            tally = tallies.get(identity)
            if tally is None:
                tally = _SetTally(codes=identity)
                tallies[identity] = tally
            tally.count += 1
            tally.composed += 1 if composed else 0
            tally.blocks.add(block.block_id)
            if not composed and tally.matched_rule is None:
                tally.matched_rule = _rule_for(identity, rules)
            # The first carded cell fixes the text and the classes shown for
            # the set. They are a property of the set, not of the cell: the
            # fold reads the same catalogue rows and the same rule for every
            # cell that produced these codes.
            if tally.status is None:
                tally.status = cell.get("status")
                tally.severity = cell.get("severity")
                tally.action_type = cell.get("action_type")
                tally.text_en = cell.get("text_en")

    ordered = sorted(tallies.values(), key=lambda t: (-t.count, t.codes))
    shown = ordered[:top_sets]
    rest = ordered[top_sets:]

    fired_labels = {t.matched_rule for t in ordered if t.matched_rule}
    rule_labels = [rule_label(r) for r in rules]
    never_fired = [label for label in rule_labels if label not in fired_labels]

    return {
        "scope": scope,
        "blocks_evaluated": len(counted),
        "blocks_not_targeted": len(not_targeted),
        "blocks_failed": len(failed),
        "block_failures": [
            {
                "block_id": str(b.block_id),
                "block_name": b.block_name,
                "error": b.error,
            }
            for b in failed
        ],
        "cells_evaluated": cells_evaluated,
        "cells_no_findings": cells_healthy,
        "cells_no_findings_pct": _pct(cells_healthy, cells_evaluated),
        "cells_carded": cells_carded,
        "cells_errored": cells_errored,
        "cells_errored_pct": _pct(cells_errored, cells_evaluated),
        "finding_sets": [
            {
                "codes": list(t.codes),
                "label": set_label(t.codes),
                "count": t.count,
                "share_pct": _pct(t.count, cells_evaluated),
                "matched_rule": t.matched_rule,
                "composed": t.composed == t.count,
                "composed_count": t.composed,
                "blocks": len(t.blocks),
                "status": t.status,
                "severity": t.severity,
                "action_type": t.action_type,
                "text_en": t.text_en,
            }
            for t in shown
        ],
        "other_sets": {
            "sets": len(rest),
            "cells": sum(t.count for t in rest),
        },
        "rules_defined": len(rules),
        "rules_fired": len(rules) - len(never_fired),
        "rules_never_fired": never_fired,
        "composed_cells": cells_composed,
        "composed_share_pct": _pct(cells_composed, cells_carded),
        "errors": {
            "count": cells_errored,
            "by_node": [
                {
                    "node_id": node,
                    "count": count,
                    "share_pct": _pct(count, cells_errored),
                    "example": error_examples.get(node),
                }
                for node, count in errors.most_common()
            ],
        },
        "timing": {
            "total_ms": round(total_ms, 1),
            "per_cell_ms": round(total_ms / cells_evaluated, 3) if cells_evaluated else 0.0,
            "includes": (
                "the per-block data loads as well as the walk, because the " "sweep pays those too"
            ),
            "slowest_blocks": [
                {
                    "block_id": str(b.block_id),
                    "block_name": b.block_name,
                    "farm_name": b.farm_name,
                    "cells": len(b.cells),
                    "duration_ms": round(b.duration_ms, 1),
                }
                for b in sorted(counted, key=lambda b: -b.duration_ms)[:10]
            ],
            "node_timing": {
                "available": False,
                "reason": (
                    "folding_engine.walk_tree has no timing hook, so no caller "
                    "outside it can attribute time to a node. The walk itself "
                    "is now kept, which is what coverage_by_node counts"
                ),
            },
        },
        "coverage_by_node": _coverage_rows(coverage, nodes, cells_evaluated),
        "never_reached": _never_reached(coverage, nodes),
    }


def _node_label(nodes: Mapping[str, Any] | None, node_id: str) -> tuple[str, str | None]:
    """One node's kind and its own label, off the compiled body.

    Falls back to ``unknown`` rather than raising. A run's coverage is still
    worth reading when it names a node the tree no longer has, and saying so
    beats dropping the row.
    """
    node = (nodes or {}).get(node_id)
    if not isinstance(node, Mapping):
        return "unknown", None
    return kind_of_node(node) or "unknown", node.get("label_en")


def _coverage_rows(
    coverage: Mapping[str, int], nodes: Mapping[str, Any] | None, cells: int
) -> list[dict[str, Any]]:
    """Every node a cell reached, most walked first."""
    rows: list[dict[str, Any]] = []
    for node_id, count in sorted(coverage.items(), key=lambda kv: (-kv[1], kv[0])):
        kind, label = _node_label(nodes, node_id)
        rows.append(
            {
                "node_id": node_id,
                "kind": kind,
                "label_en": label,
                "cells": count,
                "share_pct": _pct(count, cells),
            }
        )
    return rows


def _never_reached(
    coverage: Mapping[str, int], nodes: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """The nodes no cell in the estate walked through.

    The useful half of coverage. It names the branches of the tree this
    tenant's estate never exercised, which is what an author wants to know
    after a first run: either the check is dead, or the condition in front of
    it is wrong.

    Empty rather than the whole tree when no coverage was collected. A run
    that did not count cannot report that every node was missed.
    """
    if not nodes or not coverage:
        return []
    rows: list[dict[str, Any]] = []
    for node_id in sorted(nodes):
        if node_id in coverage:
            continue
        kind, label = _node_label(nodes, node_id)
        rows.append({"node_id": node_id, "kind": kind, "label_en": label})
    return rows


def _rule_for(identity: Sequence[str], rules: Sequence[CombinationRule]) -> str | None:
    """The rule whose set equals this identity, by label.

    Matched on the set rather than read from the cell's ``rule_code`` because
    a rule may be written without a code. Such a rule fires and the cell comes
    back with ``composed`` false and ``rule_code`` None, and counting rules
    fired from ``rule_code`` alone would report it as never fired.
    """
    wanted = frozenset(identity)
    for rule in rules:
        if rule.codes == wanted:
            return rule_label(rule)
    return None


# --- persistence -----------------------------------------------------------


class EstateDryRunRepository:
    """Reads and writes for the report row, and for real run results.

    Raw SQL against the tenant schema, the way the rest of this module's
    repositories work. The session carries the search path; nothing here
    names the schema.
    """

    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._tenant = tenant_session

    async def open_run(
        self,
        *,
        tree_id: UUID,
        tree_code: str,
        tree_name: str | None,
        version_id: UUID | None,
        scope: str,
        requested_by: UUID | None,
    ) -> UUID:
        """Insert the ``running`` row and return its id.

        The id goes back to the caller straight away: the run can take minutes
        over a large tenant, and a request that held open until the last cell
        was folded would time out at the proxy long before the report existed.
        """
        row = (
            await self._tenant.execute(
                text(
                    """
                    INSERT INTO decision_tree_estate_dry_runs
                        (tree_id, tree_code, tree_name, version_id, scope,
                         state, requested_by)
                    VALUES (:tree_id, :tree_code, :tree_name, :version_id, :scope,
                            'running', :requested_by)
                    RETURNING id
                    """
                ).bindparams(
                    bindparam("tree_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("version_id", type_=PG_UUID(as_uuid=True)),
                    bindparam("requested_by", type_=PG_UUID(as_uuid=True)),
                ),
                {
                    "tree_id": tree_id,
                    "tree_code": tree_code,
                    "tree_name": tree_name,
                    "version_id": version_id,
                    "scope": scope,
                    "requested_by": requested_by,
                },
            )
        ).scalar_one()
        return UUID(str(row))

    async def close_run(
        self,
        *,
        run_id: UUID,
        report: Mapping[str, Any],
        duration_ms: int,
    ) -> None:
        """Store the report and mark the run done."""
        await self._tenant.execute(
            text(
                """
                UPDATE decision_tree_estate_dry_runs
                   SET state = 'done',
                       finished_at = public.app_now(),
                       duration_ms = :duration_ms,
                       blocks_evaluated = :blocks_evaluated,
                       blocks_failed = :blocks_failed,
                       cells_evaluated = :cells_evaluated,
                       cells_errored = :cells_errored,
                       report = CAST(:report AS jsonb)
                 WHERE id = :run_id
                """
            ).bindparams(bindparam("run_id", type_=PG_UUID(as_uuid=True))),
            {
                "run_id": run_id,
                "duration_ms": duration_ms,
                "blocks_evaluated": int(report.get("blocks_evaluated") or 0),
                "blocks_failed": int(report.get("blocks_failed") or 0),
                "cells_evaluated": int(report.get("cells_evaluated") or 0),
                "cells_errored": int(report.get("cells_errored") or 0),
                "report": _as_json(report),
            },
        )

    async def fail_run(self, *, run_id: UUID, error: str) -> None:
        """Mark a run failed, keeping whatever it had counted."""
        await self._tenant.execute(
            text(
                """
                UPDATE decision_tree_estate_dry_runs
                   SET state = 'failed',
                       finished_at = public.app_now(),
                       error = :error
                 WHERE id = :run_id
                """
            ).bindparams(bindparam("run_id", type_=PG_UUID(as_uuid=True))),
            {"run_id": run_id, "error": error[:2000]},
        )

    async def get_run(self, *, run_id: UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._tenant.execute(
                    text(
                        """
                        SELECT id, tree_id, tree_code, tree_name, version_id, scope,
                               state, requested_by, started_at, finished_at,
                               duration_ms, blocks_evaluated, blocks_failed,
                               cells_evaluated, cells_errored, report, error
                        FROM decision_tree_estate_dry_runs
                        WHERE id = :run_id
                        """
                    ).bindparams(bindparam("run_id", type_=PG_UUID(as_uuid=True))),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row is not None else None

    async def list_runs(self, *, tree_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
        """This tree's runs, newest first, without the report document.

        The list view shows the headline counts. ``report`` is tens of
        kilobytes and only ever read one run at a time.
        """
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                        SELECT id, tree_id, tree_code, tree_name, version_id, scope,
                               state, requested_by, started_at, finished_at,
                               duration_ms, blocks_evaluated, blocks_failed,
                               cells_evaluated, cells_errored, error
                        FROM decision_tree_estate_dry_runs
                        WHERE tree_id = :tree_id
                        ORDER BY started_at DESC, id DESC
                        LIMIT :limit
                        """
                    ).bindparams(bindparam("tree_id", type_=PG_UUID(as_uuid=True))),
                    {"tree_id": tree_id, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def list_real_run_results(
        self,
        *,
        tree_id: UUID,
        run_id: UUID | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """What real runs of this tree produced, grouped by block and set.

        Read from ``decision_tree_eval_traces`` and its three fold columns
        (tenant migration 0095): ``finding_set``, ``matched_rule`` and
        ``registered_by``. Under folding the walk always ends at ``stop``, so
        nothing here derives anything from the last node — ``finding_set`` is
        the answer and the node path is only ever the explanation.

        ``node_path`` and ``resolved_values`` are not selected: a page of full
        walks is megabytes of JSONB that this view never renders.
        """
        clauses = ["t.tree_id = :tree_id"]
        params: dict[str, Any] = {"tree_id": tree_id, "limit": limit}
        binds = [bindparam("tree_id", type_=PG_UUID(as_uuid=True))]
        if run_id is not None:
            clauses.append("t.run_id = :run_id")
            params["run_id"] = run_id
            binds.append(bindparam("run_id", type_=PG_UUID(as_uuid=True)))
        where_sql = " WHERE " + " AND ".join(clauses)
        # S608: every fragment is a literal from the closed set above and
        # every value travels as a bind parameter.
        sql = (
            "SELECT t.run_id, "  # noqa: S608
            "       t.block_id, "
            "       COALESCE(b.name, b.code) AS block_name, "
            "       COALESCE(NULLIF(b.name_ar, ''), b.name, b.code) AS block_name_ar, "
            "       t.farm_id, "
            "       COALESCE(f.name, '') AS farm_name, "
            "       t.tree_id, t.tree_code, t.tree_version, "
            # A verdict row carries no tree name. The catalogue row in
            # `public` is the only place it exists, so the join is what makes
            # the screen readable; without it the column reads as a code.
            "       dt.name_en AS tree_name, "
            "       dt.name_ar AS tree_name_ar, "
            "       t.scope, t.status, "
            "       t.finding_set, t.matched_rule, t.registered_by, "
            "       count(*) AS cells, "
            "       count(DISTINCT t.recommendation_id) "
            "         FILTER (WHERE t.recommendation_id IS NOT NULL) AS cards_opened, "
            # `min()` has no uuid overload in Postgres. One id of the group is
            # all this column is for — the row links to the card it opened —
            # so the first of the aggregated ids is the answer.
            "       (array_agg(t.recommendation_id) "
            "          FILTER (WHERE t.recommendation_id IS NOT NULL))[1] "
            "         AS recommendation_id, "
            "       max(t.evaluated_at) AS last_evaluated_at, "
            "       count(*) FILTER (WHERE t.error IS NOT NULL) AS errored "
            "FROM decision_tree_eval_traces t "
            "LEFT JOIN blocks b ON b.id = t.block_id "
            "LEFT JOIN farms f ON f.id = t.farm_id "
            "LEFT JOIN public.decision_trees dt ON dt.id = t.tree_id"
            f"{where_sql} "
            "GROUP BY t.run_id, t.block_id, b.name, b.name_ar, b.code, t.farm_id, "
            "         f.name, t.tree_id, t.tree_code, t.tree_version, dt.name_en, "
            "         dt.name_ar, t.scope, t.status, t.finding_set, t.matched_rule, "
            "         t.registered_by "
            "ORDER BY max(t.evaluated_at) DESC, count(*) DESC "
            "LIMIT :limit"
        )
        rows = (await self._tenant.execute(text(sql).bindparams(*binds), params)).mappings().all()
        return [dict(r) for r in rows]


def _as_json(value: Mapping[str, Any]) -> str:
    import json

    return json.dumps(value, default=str)


# --- the run ---------------------------------------------------------------


class EstateDryRunService:
    """Runs one beta tree over one tenant's whole estate and stores the report.

    The unit of work is ``FoldingTreeAuthorService.dry_run`` — one block, every
    cell, no writes. Calling it per block rather than reimplementing the fold
    keeps one definition of what a dry run is: if the author's per-block panel
    and this report ever disagreed, neither could be trusted.
    """

    def __init__(
        self,
        *,
        author_service: Any,
        tenant_session: AsyncSession,
        tenant_schema: str | None,
    ) -> None:
        self._author = author_service
        self._tenant = tenant_session
        self._schema = tenant_schema
        self._repo = EstateDryRunRepository(tenant_session=tenant_session)

    async def run(
        self,
        *,
        tree_id: UUID,
        run_id: UUID,
        block_limit: int | None = None,
    ) -> dict[str, Any]:
        """Fold every active block and return the report.

        ``block_limit`` exists for the integration tests and for a first look
        at a large tenant. It takes the first N blocks in farm and block order,
        so two runs with the same limit cover the same blocks.
        """
        from app.modules.recommendations.folding_engine import parse_combination_rules
        from app.modules.recommendations.repository import RecommendationsRepository

        repo = RecommendationsRepository(
            tenant_session=self._tenant, public_session=self._author._public
        )
        blocks = await repo.list_blocks_for_targeting()
        if block_limit is not None:
            blocks = blocks[:block_limit]

        compiled, version_id, scope = await self._compiled_tree(tree_id)
        rules = parse_combination_rules(compiled.get("combinations"))

        started = time.perf_counter()
        folds: list[BlockFold] = []
        for row in blocks:
            folds.append(await self._fold_block(tree_id=tree_id, row=row))
        total_ms = (time.perf_counter() - started) * 1000.0

        report = build_estate_report(
            blocks=folds,
            rules=rules,
            scope=scope,
            total_ms=total_ms,
            nodes=compiled.get("nodes") or {},
        )
        report["tree_id"] = str(tree_id)
        report["version_id"] = str(version_id) if version_id else None
        report["run_id"] = str(run_id)
        await self._repo.close_run(run_id=run_id, report=report, duration_ms=int(total_ms))
        return report

    async def _fold_block(self, *, tree_id: UUID, row: Mapping[str, Any]) -> BlockFold:
        """One block's fold, timed, with a failure kept as a row rather than raised.

        A block whose imagery or weather load fails must not end the run: the
        tenant has dozens of blocks and the report is the reason to run at all.
        The failure is counted and named instead.
        """
        block_id = row["block_id"]
        started = time.perf_counter()
        try:
            result = await self._author.dry_run(
                tree_id=tree_id,
                block_id=block_id,
                definition=None,
                version_id=None,
                tenant_session=self._tenant,
                tenant_schema=self._schema,
                collect_coverage=True,
            )
        # One bad block must not end the run: the tenant has dozens and the
        # report is the reason to run at all.
        except Exception as exc:
            _log.warning(
                "estate_dry_run_block_failed",
                block_id=str(block_id),
                tree_id=str(tree_id),
                error=str(exc),
            )
            return BlockFold(
                block_id=block_id,
                block_name=row.get("block_name") or row.get("block_code"),
                farm_id=row.get("farm_id"),
                farm_name=row.get("farm_name"),
                targeted=False,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                error=str(exc),
            )
        targeting = result.get("targeting") or {}
        return BlockFold(
            block_id=block_id,
            block_name=row.get("block_name") or row.get("block_code"),
            farm_id=row.get("farm_id"),
            farm_name=row.get("farm_name"),
            targeted=bool(targeting.get("matched")),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            cells=tuple(result.get("cells") or ()),
            node_counts=dict(result.get("node_counts") or {}),
        )

    async def _compiled_tree(self, tree_id: UUID) -> tuple[dict[str, Any], UUID | None, str]:
        """The version this run folds: the published one, else the newest draft.

        The same order the per-block dry run uses, so the estate report and the
        author's panel fold the same tree.
        """
        from app.modules.recommendations.folding_authoring import BetaDryRunUnavailableError

        tree = await self._author.get_tree(tree_id)
        repo = self._author._repo
        row = None
        if tree.get("current_version_id") is not None:
            row = await repo.get_version(tree["current_version_id"])
        if row is None:
            row = await repo.get_latest_version(tree_id=tree_id)
        if row is None:
            raise BetaDryRunUnavailableError("This tree has no version to run.")
        compiled = row["tree_compiled"] or {}
        return compiled, row["id"], str(compiled.get("scope") or "block")


def get_estate_dry_run_service(
    *,
    author_service: Any,
    tenant_session: AsyncSession,
    tenant_schema: str | None,
) -> EstateDryRunService:
    return EstateDryRunService(
        author_service=author_service,
        tenant_session=tenant_session,
        tenant_schema=tenant_schema,
    )


# --- starting a run, and reading one, from a platform caller ----------------
#
# A platform admin has no tenant session: their JWT carries no tenant, so the
# request-scoped dependency points at `public` alone. Every route below is a
# platform route that names its tenant explicitly, so each one opens its own
# session and sets the search path to that tenant's schema. This is the same
# thing the Celery tasks do, for the same reason, and it is why a platform
# admin reading a tenant's report does not get the empty list that a
# tenant-only route would have handed them.


@asynccontextmanager
async def tenant_scoped_session(tenant_schema: str) -> AsyncIterator[AsyncSession]:
    """One session pointed at one tenant's schema, committed on exit."""
    from app.shared.db.session import AsyncSessionLocal, sanitize_tenant_schema

    safe = sanitize_tenant_schema(tenant_schema)
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :v, TRUE)"),
            {"v": safe},
        )
        yield session


async def start_estate_dry_run(
    *,
    tenant_schema: str,
    tenant_id: UUID,
    tree_id: UUID,
    tree_code: str,
    tree_name: str | None,
    version_id: UUID | None,
    scope: str,
    author_tenant_id: UUID | None,
    requested_by: UUID | None,
    block_limit: int | None = None,
) -> UUID:
    """Insert the ``running`` row, queue the task, and return the run id.

    The row is inserted in its own committed transaction before the task is
    queued. A worker is free to pick the task up in the same millisecond, and
    a task that began against an uncommitted row would fail to find the run it
    was asked to fill in.
    """
    from app.modules.recommendations.folding_report_tasks import estate_dry_run

    async with tenant_scoped_session(tenant_schema) as session:
        run_id = await EstateDryRunRepository(tenant_session=session).open_run(
            tree_id=tree_id,
            tree_code=tree_code,
            tree_name=tree_name,
            version_id=version_id,
            scope=scope,
            requested_by=requested_by,
        )
    estate_dry_run.delay(
        tenant_schema,
        str(tenant_id),
        str(tree_id),
        str(run_id),
        str(author_tenant_id) if author_tenant_id else None,
        block_limit,
    )
    _log.info(
        "estate_dry_run_queued",
        tenant_schema=tenant_schema,
        tree_id=str(tree_id),
        run_id=str(run_id),
    )
    return run_id
