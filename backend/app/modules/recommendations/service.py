"""Recommendations service — public Protocol + concrete impl + factory.

Three responsibilities:

  * **Engine driver**: ``evaluate_block`` loads every active decision
    tree, builds a ``ConditionContext`` from the block's latest signals,
    walks each tree, and inserts an open recommendation per non-trivial
    leaf (action_type != 'no_action'). Idempotent on the partial UNIQUE
    `(block_id, tree_id) WHERE state='open'`.
  * **State transitions**: ``transition_recommendation`` moves a
    recommendation through open → applied / dismissed / deferred /
    expired with audit + event publishes.
  * **Catalog reads**: surface decision-tree definitions for the API.

The Beat task in ``tasks.py`` is the only caller for tenant-wide
sweeps; everything else (admin endpoints, on-demand evaluation) goes
through this service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.farms.attribute_snapshot import load_crop_attribute_snapshot
from app.modules.grid.snapshot import load_snapshot as load_grid_snapshot
from app.modules.recommendations.engine import (
    EvaluationResult,
    TreeOutcome,
    TreePathStep,
    evaluate_tree,
)
from app.modules.recommendations.errors import (
    BlockNotInFarmError,
    DecisionTreeNotFoundError,
    DecisionTreeNotRunnableError,
    FarmNotFoundError,
    GroupMemberNotActionableError,
    InvalidRecommendationTransitionError,
    RecommendationNotFoundError,
)
from app.modules.recommendations.events import (
    EvaluationRunFinishedV1,
    RecommendationAppliedV1,
    RecommendationDeferredV1,
    RecommendationDismissedV1,
    RecommendationOpenedV1,
)
from app.modules.recommendations.findings import (
    PLATFORM_SOURCE,
    TENANT_SOURCE,
    FindingDef,
    resolve_findings,
    shadowed_codes,
)
from app.modules.recommendations.folding_engine import (
    CombinationRule,
    FoldedCard,
    FoldingWalkResult,
    UnknownFindingError,
    fold,
    parse_combination_rules,
)
from app.modules.recommendations.folding_engine import walk_tree as walk_folding_tree
from app.modules.recommendations.narrative import compose_both
from app.modules.recommendations.repository import (
    FindingsRepository,
    RecommendationsRepository,
)
from app.modules.recommendations.status_codes import (
    STATUS_BY_CODE,
    STATUS_DEFINITIONS,
    worst,
)
from app.modules.signals.snapshot import load_snapshot as load_signals_snapshot
from app.modules.weather.snapshot import load_index_snapshot as load_weather_index_snapshot
from app.modules.weather.snapshot import load_risk_snapshot as load_weather_risk_snapshot
from app.modules.weather.snapshot import load_snapshot as load_weather_snapshot
from app.modules.weather.snapshot import load_water_balance_snapshot
from app.shared import clock
from app.shared.action_items import build_group_key
from app.shared.conditions import ConditionContext
from app.shared.crop_taxonomy import path_matches
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus


@dataclass(slots=True)
class _BlockEvaluation:
    """Everything needed to walk trees against one block.

    Built once by ``_prepare_block_evaluation`` and shared by the
    write path (``evaluate_block``) and the read-only explain path
    (``explain_block``) so the two can never drift on targeting,
    context construction or parameter overrides.
    """

    farm_id: UUID
    block_crop_id: UUID | None
    crop_path: str | None
    growth_stage: str | None
    soil_texture: str | None
    salinity_class: str | None
    latest: dict[str, Any]
    weather: Any
    weather_indices: Any
    weather_risks: Any
    signals: Any
    grid: Any
    crop_attributes: dict[str, Any]
    ctx: ConditionContext
    block_trees: list[dict[str, Any]]
    cell_trees: list[dict[str, Any]]
    # Trees excluded by multi-axis targeting (crop / country / soil), each
    # paired with the verdict naming the axis that rejected it. Kept so the
    # explain endpoint and the trace can both answer "why is nothing running
    # here?" with the axis and both sides of the comparison.
    skipped_trees: list[tuple[dict[str, Any], TargetingVerdict]]
    param_overrides_per_tree: dict[UUID, dict[str, Any]]
    # Defaulted, unlike its siblings: this source arrived after the dataclass
    # and after every construction site in the tests. `None` is also the
    # honest value for a block the water-balance sweep has not written, which
    # is what a fail-closed predicate needs to see.
    water_balance: Any = None

    def cell_context(self, cell_means: Any) -> ConditionContext:
        """Block context with this cell's imagery means swapped in."""
        return ConditionContext.from_block_signals(
            block_id=self.ctx.block_id,
            block_attributes={
                "growth_stage": self.growth_stage,
                "soil_texture": self.soil_texture,
                "salinity_class": self.salinity_class,
            },
            latest_index_aggregates=_merge_cell_means(self.latest, cell_means),
            weather=self.weather,
            weather_indices=self.weather_indices,
            weather_risks=self.weather_risks,
            water_balance=self.water_balance,
            signals=self.signals,
            grid=self.grid,
            crop_attributes=self.crop_attributes,
        )


# Statuses whose rows carry the full JSONB payload (node path + every resolved
# ref). `clear` keeps the path but drops the values, and `skipped` never walked
# at all — see migration 0062 for why the grain is uneven.
_FULL_PAYLOAD_STATUSES = frozenset({"fired", "error"})

# What a folding walk that collected nothing says. The tree ran, the checks all
# came out clean, and that is an answer — the same one a `status` leaf gives.
_NO_FINDINGS_EN = "Checked; no findings."
_NO_FINDINGS_AR = "تم الفحص؛ لا توجد ملاحظات."

# `recommendations.action_type` is check constrained (tenant 0015). A finding
# catalogue row could name a verb outside that list, and the insert would then
# fail for the whole block rather than for the one card. `other` is the honest
# landing place: work is asked for, and the board has no more specific column.
_ALLOWED_ACTION_TYPES: frozenset[str] = frozenset(
    {"irrigate", "fertilize", "spray", "scout", "harvest_window", "prune", "no_action", "other"}
)


# What a folded card becomes, by its status. Anything not listed writes a
# verdict and nothing else.
_FOLD_KIND_BY_STATUS: dict[str, str] = {"alert": "alert", "issue": "recommendation"}


def _is_folding_shape(compiled: Any) -> bool:
    """True when this compiled body is a folding tree.

    The same two-line rule the compiler's ``is_folding_shape`` applies: a node
    map holding any node with a ``register`` or a ``stop`` key. It is not
    imported, because the compiler lands in a separate change; the rule is the
    contract, and it is spelled the same way in both places on purpose.
    """
    nodes = compiled.get("nodes") if isinstance(compiled, Mapping) else None
    if not isinstance(nodes, Mapping):
        return False
    return any(isinstance(n, Mapping) and ("register" in n or "stop" in n) for n in nodes.values())


@dataclass(frozen=True, slots=True)
class _FindingRow:
    """One finding catalogue entry, as the fold reads it.

    Structurally the ``FindingDef`` protocol in ``folding_engine``. Declared
    here rather than imported because the catalogue tables and their module
    land in a separate change; when they do, this class is replaced by that
    module's row and the only thing that must match is the attribute names.
    """

    code: str
    clause_en: str
    clause_ar: str | None
    name_en: str
    name_ar: str | None
    default_status: str
    source: str
    action_type: str | None = None
    actions: dict[str, list[dict[str, Any]]] | None = None


def _finding_rows_from(raw: Any, *, source: str) -> dict[str, _FindingRow]:
    """Read a ``findings:`` block, or a set of catalogue rows, into the fold's
    catalogue shape.

    Accepts either a mapping of code to entry or a list of entries carrying
    their own ``code``. A malformed entry is skipped rather than raised on: a
    missing clause is caught where it matters, at the fold, which refuses to
    build a card out of a code it cannot put into a sentence.
    """
    entries: list[tuple[str, Any]] = []
    if isinstance(raw, Mapping):
        entries = [(str(k), v) for k, v in raw.items()]
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, Mapping) and isinstance(entry.get("code"), str):
                entries.append((str(entry["code"]), entry))

    out: dict[str, _FindingRow] = {}
    for code, entry in entries:
        if not isinstance(entry, Mapping):
            continue
        clause_en = entry.get("clause_en")
        if not isinstance(clause_en, str) or not clause_en:
            continue
        actions = entry.get("actions")
        out[code] = _FindingRow(
            code=code,
            clause_en=clause_en,
            clause_ar=entry.get("clause_ar") if isinstance(entry.get("clause_ar"), str) else None,
            name_en=str(entry.get("name_en") or code),
            name_ar=entry.get("name_ar") if isinstance(entry.get("name_ar"), str) else None,
            default_status=str(entry.get("default_status") or "issue"),
            source=source,
            action_type=(
                entry.get("action_type") if isinstance(entry.get("action_type"), str) else None
            ),
            actions=dict(actions) if isinstance(actions, Mapping) else None,
        )
    return out


def _folding_path_steps(walk: FoldingWalkResult) -> list[TreePathStep]:
    """The folding walk's path in the shape the stored ``tree_path`` uses.

    A folding walk visits node kinds the old path never had, and what each one
    did is in ``detail`` — the finding a register wrote, the case a switch
    chose. Both are carried inside the step's values map, because that map is
    free-form JSONB and the detail is the part of a folding walk anybody
    reading the card actually wants.
    """
    steps: list[TreePathStep] = []
    for step in walk.path:
        values: dict[str, Any] = dict(step.condition_snapshot or {})
        values["kind"] = step.kind
        if step.detail:
            values["detail"] = dict(step.detail)
        steps.append(
            TreePathStep(
                node_id=step.node_id,
                matched=step.matched,
                label_en=step.label_en,
                label_ar=step.label_ar,
                condition_snapshot=values,
            )
        )
    return steps


def _folding_evaluation(walk: FoldingWalkResult, card: FoldedCard | None) -> EvaluationResult:
    """Dress one folding walk plus its fold as an ``EvaluationResult``.

    Everything downstream of the walk — the trace, the verdict, the card
    insert, the audit row, the event — is written once, for both engines. This
    adapter is what lets that stay true: a folded card becomes the same
    ``TreeOutcome`` an old-style leaf produces, so there is one persistence
    path rather than two that have to be kept in step.

    An empty finding set is a ``status`` outcome, not a missing one. The tree
    ran and found nothing, which is the same sentence a status leaf writes and
    the same colour on the map.
    """
    path = _folding_path_steps(walk)
    snapshot = dict(walk.evaluation_snapshot)
    if not walk.ok:
        # `ok` is both halves: no error, and a stop node actually reached. A
        # walk that ended anywhere else never said it was finished, and its
        # findings must not be read as a complete set.
        return EvaluationResult(
            outcome=None,
            path=path,
            error=walk.error or "the walk ended without reaching a stop node",
            evaluation_snapshot=snapshot,
        )

    if card is None:
        outcome = TreeOutcome(
            action_type="no_action",
            severity="info",
            confidence=Decimal("1"),
            parameters={},
            text_en=_NO_FINDINGS_EN,
            text_ar=_NO_FINDINGS_AR,
            valid_for_hours=None,
            kind="status",
            status_code="good",
            leaf_node_id=walk.stopped_at,
        )
        return EvaluationResult(outcome=outcome, path=path, evaluation_snapshot=snapshot)

    # The fold's status decides both what the map paints and what, if
    # anything, opens in the Action Center:
    #
    #   alert                 -> an alert, red on the map
    #   issue                 -> a recommendation, amber on the map
    #   good, very_good, na   -> no work item; the verdict alone says what
    #                            the cell is, with the findings' own words
    #
    # A status outside the vocabulary cannot come out of the fold, which
    # ranks against `status_codes`; `issue` is the landing place if one does,
    # because it asks a person to look without raising an alarm.
    status = card.status if card.status in STATUS_BY_CODE else "issue"
    kind = _FOLD_KIND_BY_STATUS.get(status, "status")
    action_type = card.action_type if card.action_type in _ALLOWED_ACTION_TYPES else "other"
    outcome = TreeOutcome(
        # `no_action` is what keeps a good or very good card off the board:
        # the dispatcher opens no work item for it and writes the verdict.
        action_type=action_type if kind != "status" else "no_action",
        severity=card.severity,
        # A fold asserts what the checks found; it does not estimate a
        # probability the way a leaf's `confidence:` does. The column is NOT
        # NULL, so the honest value is 1.
        confidence=Decimal("1"),
        parameters={
            "finding_set": list(card.identity),
            # The same value as `status_code` since the fold learned the
            # five-value vocabulary. Kept under its old name because cards
            # already written carry it.
            "health_status": status,
            "matched_rule": card.rule_code,
            "composed": card.composed,
        },
        text_en=card.text_en,
        text_ar=card.text_ar,
        valid_for_hours=None,
        kind=kind,
        status_code=status,
        leaf_node_id=walk.stopped_at,
        actions={k: list(v) for k, v in card.actions.items()},
    )
    return EvaluationResult(outcome=outcome, path=path, evaluation_snapshot=snapshot)


def _alert_rule_leaf(outcome: TreeOutcome) -> str:
    """The last segment of a tree alert's ``rule_code``.

    An old-style leaf is its own identity. A folding walk almost always ends
    at the same stop node, so the stop node cannot tell one alert from
    another; the finding set can, and it is what the dedup index must see. A
    block whose findings changed gets a new alert with the new words, instead
    of a bump on an alert that describes yesterday's findings. The segment
    holds no colon, so ``tree:<code>:`` still splits the way every reader of
    ``rule_code`` expects.
    """
    finding_set = (outcome.parameters or {}).get("finding_set")
    if finding_set:
        return "findings=" + "+".join(str(c) for c in finding_set)
    return outcome.leaf_node_id or "leaf"


def _fold_trace_columns(walk: FoldingWalkResult | None, card: FoldedCard | None) -> dict[str, Any]:
    """The three short columns every trace row carries (tenant 0094).

    Empty for a tree the old engine walked, which has no findings at all —
    ``[]`` and ``{}`` rather than null, so a reader never has to tell "this
    tree does not fold" from "this column was not written".
    """
    if walk is None:
        return {"finding_set": [], "matched_rule": None, "registered_by": {}}
    return {
        "finding_set": list(card.identity) if card is not None else [],
        "matched_rule": card.rule_code if card is not None else None,
        "registered_by": {f.code: list(f.registered_by) for f in walk.findings},
    }


def _notify_on_supersede(
    *, old_codes: Sequence[str], old_severity: str, new_codes: Sequence[str], new_severity: str
) -> bool:
    """Whether a replaced card is worth a notification (design 5.6).

    A set that gained a code says something new is wrong. A severity that rose
    says the same thing about something already known. A set that only lost a
    code is silent: a shrinking set never asks for more work, and a second
    email about less work is how people learn to ignore the first.
    """
    gained = set(new_codes) - set(old_codes)
    rose = _SEVERITY_RANK.get(new_severity, 0) > _SEVERITY_RANK.get(old_severity, 0)
    return bool(gained) or rose


# The guard on one window read. Not a page size: a farm past this has more
# history than a day-by-day replay can draw, and the caller is told so
# rather than handed a short list it cannot tell from a complete one.
_HISTORY_ROW_LIMIT = 50_000


@dataclass(slots=True)
class _VerdictBuffer:
    """Accumulates one block's verdicts, then writes them in three statements.

    A verdict is what every evaluation leaves behind, including the ones that
    open nothing. Before this existed a leaf that found nothing wrong wrote no
    row anywhere, so "checked and fine", "excluded by targeting" and "never
    ran" were the same blank on screen.

    Buffered for the same reason the traces are: a cell-scoped tree over a
    121-cell grid produces 121 verdicts for one block, and a round trip each
    would cost more than the evaluation.

    ``seen_trees`` and ``seen_cells`` are the other half of the write. A row
    that was NOT produced this pass has to be closed, and that is invisible to
    a loop over the rows that were.
    """

    run_id: UUID | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    seen_trees: set[UUID] = field(default_factory=set)
    seen_cells: dict[UUID, list[UUID]] = field(default_factory=dict)

    def add(
        self,
        *,
        tree: dict[str, Any],
        farm_id: UUID,
        block_id: UUID,
        cell_id: UUID | None,
        outcome: TreeOutcome,
        alert_id: UUID | None = None,
        recommendation_id: UUID | None = None,
    ) -> None:
        tree_id = tree["tree_id"]
        self.seen_trees.add(tree_id)
        if cell_id is not None:
            self.seen_cells.setdefault(tree_id, []).append(cell_id)
        self.rows.append(
            {
                "farm_id": farm_id,
                "block_id": block_id,
                "cell_id": cell_id,
                "scope": "cell" if cell_id is not None else "block",
                "tree_id": tree_id,
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "leaf_node_id": outcome.leaf_node_id or "",
                "kind": outcome.kind,
                "status_code": outcome.status_code,
                # Only the two kinds that ask for work carry one; the table's
                # CHECK refuses the other combinations either way.
                "severity": (
                    outcome.severity if outcome.kind in ("alert", "recommendation") else None
                ),
                "text_en": outcome.text_en,
                "text_ar": outcome.text_ar,
                "alert_id": alert_id,
                "recommendation_id": recommendation_id,
            }
        )


@dataclass(slots=True)
class _TraceBuffer:
    """Accumulates one block's evaluation traces for a single bulk insert.

    A cell-scoped tree over a 121-cell grid produces 121 rows for one block;
    inserting them one at a time would put the trace write on the same order
    as the evaluation itself. Rows are appended during the walk and flushed
    once, at the end of the block.
    """

    run_id: UUID
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        *,
        tree: dict[str, Any],
        farm_id: UUID,
        block_id: UUID,
        cell_id: UUID | None,
        status: str,
        result: EvaluationResult | None = None,
        verdict: TargetingVerdict | None = None,
        overrides: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        recommendation_id: UUID | None = None,
        alert_id: UUID | None = None,
        duration_ms: int | None = None,
        fold: dict[str, Any] | None = None,
    ) -> None:
        full = status in _FULL_PAYLOAD_STATUSES
        # Unconditional, unlike node_path and resolved_values. They are three
        # short values and they answer the first question asked of a folding
        # run: what did this walk hold at the end (tenant 0094, design 6.6).
        fold_columns = fold or {"finding_set": [], "matched_rule": None, "registered_by": {}}
        self.rows.append(
            {
                "run_id": self.run_id,
                "farm_id": farm_id,
                "block_id": block_id,
                "cell_id": cell_id,
                "tree_id": tree["tree_id"],
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "scope": tree.get("scope") or "block",
                "status": status,
                "skip_axis": verdict.axis if verdict is not None else None,
                "skip_detail": (
                    {"required": list(verdict.required), "actual": verdict.actual}
                    if verdict is not None and not verdict.matched
                    else None
                ),
                "node_path": _serialize_path(result.path) if result is not None else [],
                "resolved_values": (
                    dict(result.evaluation_snapshot) if full and result is not None else {}
                ),
                "param_overrides": dict(overrides or {}),
                "outcome": outcome,
                "recommendation_id": recommendation_id,
                "alert_id": alert_id,
                "duration_ms": duration_ms,
                "error": result.error if result is not None else None,
                "finding_set": fold_columns["finding_set"],
                "matched_rule": fold_columns["matched_rule"],
                "registered_by": fold_columns["registered_by"],
            }
        )


class RecommendationsService(Protocol):
    """Public contract."""

    async def evaluate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        tenant_id: UUID,
    ) -> dict[str, int]: ...

    async def explain_block(
        self,
        *,
        block_id: UUID,
        tenant_id: UUID,
        farm_id: UUID,
    ) -> dict[str, Any]: ...

    async def list_recommendations(
        self,
        *,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        state_filter: tuple[str, ...] = (),
        action_type_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]: ...

    async def get_recommendation(self, *, recommendation_id: UUID) -> dict[str, Any] | None: ...

    async def transition_recommendation(
        self,
        *,
        recommendation_id: UUID,
        action: str,
        dismissal_reason: str | None,
        deferred_until: datetime | None,
        outcome_notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]: ...


def _as_utc(at: datetime | None) -> datetime | None:
    """Give a caller's instant a time zone before it meets a timestamptz.

    A query string can carry `2026-09-01T00:00` with no offset, and
    subtracting a naive datetime from a timestamptz raises TypeError. The
    value the caller sent is echoed back untouched; only the comparison is
    stamped, and UTC is the stamp because every other instant in this system
    is stored that way.
    """
    if at is None:
        return None
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at


def _block_group(
    *, block_id: UUID, rows: list[dict[str, Any]], as_of: datetime | None
) -> dict[str, Any]:
    """One block's verdicts plus the two numbers a reader wants first.

    ``worst_status`` is the block's answer: the highest-ranking status any of
    its trees returned. `na` ranks 0, so a tree with nothing to say never
    outranks a real one.
    """
    return {
        "block_id": block_id,
        "as_of": as_of,
        "worst_status": worst([str(r["status_code"]) for r in rows]),
        "last_evaluated_at": (max(r["last_evaluated_at"] for r in rows) if rows else None),
        "verdicts": rows,
    }


class RecommendationsServiceImpl:
    """Tenant-session-scoped concrete service."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        public_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._tenant = tenant_session
        self._public = public_session
        self._repo = RecommendationsRepository(
            tenant_session=tenant_session, public_session=public_session
        )
        # The engine writes into `alerts` as well as `recommendations` (a leaf
        # picks which), so the grouping bookkeeping has to reach both tables.
        # Imported lazily inside the method that opens an alert; held here for
        # the sweep-level clear/recount, which runs whether or not this block
        # happened to raise an alert.
        from app.modules.alerts.repository import AlertsRepository

        self._alert_repo = AlertsRepository(
            tenant_session=tenant_session, public_session=public_session
        )
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)
        # Resolved once per service instance. A sweep walks thousands of
        # (block, cell, tree) triples and the tenant's calendar day does not
        # move under it; re-reading public.tenants for each would be one
        # cross-schema round trip per evaluation to learn the same date.
        self._today_cache: date | None = None
        # The finding catalogue, read once per service instance. A sweep folds
        # thousands of walks against the same rows, and the catalogue does not
        # move under it. None means "not read yet"; an empty dict is a real
        # answer and is not re-read.
        self._finding_catalogue_cache: dict[str, _FindingRow] | None = None

    async def _finding_catalogue(self, compiled: Mapping[str, Any]) -> dict[str, _FindingRow]:
        """The finding definitions available to one folding tree.

        Two layers, and the seam between this change and the catalogue change
        runs right through them:

        1. ``public.decision_tree_findings`` plus the tenant's own table, when
           they exist. That is where the shared vocabulary lives once the
           catalogue lands. The read is guarded on the tables being present,
           so this code runs correctly both before and after they do.
        2. The tree's own ``findings:`` block, for a tree that carries its
           definitions with it. It fills codes the tables do not hold and
           never overrides them, because the point of a shared catalogue is
           that ``dry`` means one thing everywhere.

        A code in neither layer reaches the fold as an ``UnknownFindingError``
        and the walk is recorded as an error. That is deliberate: the
        alternative is a card that prints a raw code at a grower.
        """
        if self._finding_catalogue_cache is None:
            rows = await self._repo.list_finding_catalogue()
            self._finding_catalogue_cache = {
                str(r["code"]): _FindingRow(
                    code=str(r["code"]),
                    clause_en=str(r.get("clause_en") or ""),
                    clause_ar=r.get("clause_ar"),
                    name_en=str(r.get("name_en") or r["code"]),
                    name_ar=r.get("name_ar"),
                    default_status=str(r.get("default_status") or "issue"),
                    source=str(r.get("source") or "platform"),
                )
                for r in rows
                if r.get("clause_en")
            }
        catalogue = dict(_finding_rows_from(compiled.get("findings"), source="tree"))
        for code, row in self._finding_catalogue_cache.items():
            local = catalogue.get(code)
            # The catalogue table has no action_type or actions column, so a
            # catalogue row carries None for both. Replacing the tree's row
            # wholesale would erase what the tree declared and drop the card
            # back to the fallback action type. The table wins on the shared
            # vocabulary it does define; the tree keeps the rest.
            merged = row
            if local is not None and row.action_type is None and row.actions is None:
                merged = replace(row, action_type=local.action_type, actions=local.actions)
            catalogue[code] = merged
        return catalogue

    async def _walk_and_fold(
        self,
        *,
        tree: dict[str, Any],
        eval_ctx: ConditionContext,
        overrides: dict[str, Any],
    ) -> tuple[FoldingWalkResult, FoldedCard | None]:
        """One folding walk and its fold.

        The fold is where a registered code meets the catalogue, so it is also
        where a tree published against a catalogue it no longer agrees with is
        caught. That is reported as a walk error rather than as a silent card,
        because a card missing one of its findings reads as complete.
        """
        compiled = tree["tree_compiled"]
        walk = walk_folding_tree(compiled, eval_ctx, param_overrides=overrides)
        if not walk.ok:
            return walk, None
        catalogue = await self._finding_catalogue(compiled)
        rules: list[CombinationRule] = parse_combination_rules(compiled.get("combinations"))
        try:
            card = fold(walk.findings, catalogue=catalogue, rules=rules)
        except UnknownFindingError as exc:
            walk.error = (
                f"finding code {exc.code!r} is not in the catalogue; "
                "the tree and the catalogue disagree"
            )
            return walk, None
        return walk, card

    async def _supersede_open_card(
        self,
        *,
        card: FoldedCard,
        block_id: UUID,
        cell_id: UUID | None,
        farm_id: UUID,
        tree: dict[str, Any],
        actor_user_id: UUID | None,
    ) -> tuple[UUID | None, bool]:
        """Close the open card when the finding set changed (design 5.6).

        Returns ``(superseded_id, notify)``. ``superseded_id`` is the row this
        evaluation closed, or None when there was nothing open or the open
        card still says the same thing.

        The dedup index — ``(block_id, cell_id, tree_id) WHERE state = 'open'``
        — is right as it stands and is not touched. It is what makes the close
        necessary: without it the second insert is refused with no error, and
        the card on screen keeps yesterday's words about today's field.

        The close uses ``expired``, one of the states the check constraint
        already admits. A ``superseded`` state would read better and would
        mean altering that constraint; the history row written alongside says
        which of the two happened, so nothing is lost by reusing the state.
        """
        prior_id = await self._repo.find_open_recommendation(
            block_id=block_id, tree_id=tree["tree_id"], cell_id=cell_id
        )
        if prior_id is None:
            # Nothing open. The card about to be written is new, and new work
            # is always worth announcing.
            return None, True
        prior = await self._repo.get_card_identity(recommendation_id=prior_id)
        if prior is None:
            return None, True
        if list(prior["finding_set"]) == list(card.identity):
            # The same findings again. The insert below is refused by the
            # dedup index, the recurrence counters move, and nobody is told
            # anything: they are already looking at this card.
            return None, False

        notify = _notify_on_supersede(
            old_codes=prior["finding_set"],
            old_severity=str(prior["severity"]),
            new_codes=card.identity,
            new_severity=card.severity,
        )
        await self._repo.transition_recommendation(
            recommendation_id=prior_id, new_state="expired", actor_user_id=actor_user_id
        )
        await self._repo.insert_history(
            recommendation_id=prior_id,
            block_id=block_id,
            cell_id=cell_id,
            farm_id=farm_id,
            from_state="open",
            to_state="expired",
            actor_user_id=actor_user_id,
            details={
                "reason": "superseded",
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "finding_set_before": list(prior["finding_set"]),
                "finding_set_after": list(card.identity),
                "notified": notify,
            },
        )
        self._log.info(
            "decision_tree_card_superseded",
            tree_code=tree["tree_code"],
            block_id=str(block_id),
            cell_id=str(cell_id) if cell_id else None,
            before=list(prior["finding_set"]),
            after=list(card.identity),
            notified=notify,
        )
        return prior_id, notify

    async def _today(self, tenant_schema: str) -> date:
        """Today in the tenant's timezone — the boundary streaks are cut on."""
        if self._today_cache is None:
            self._today_cache = await self._repo.tenant_today(tenant_schema=tenant_schema)
        return self._today_cache

    async def _ensure_rec_group_parent(
        self,
        *,
        block_id: UUID,
        group_key: str,
        today: date,
        actor_user_id: UUID | None,
        insert: Any,
    ) -> tuple[UUID | None, bool]:
        """The single row a block's firing cells aggregate into.

        Returns ``(parent_id, created)``. Every cell of the block calls this,
        so the bump inside it runs many times per pass — harmless by
        construction, because the counters move on a change of calendar day and
        not on a call.
        """
        existing = await self._repo.find_open_group_parent(block_id=block_id, group_key=group_key)
        if existing is not None:
            await self._repo.bump_recurrence(
                row_id=existing, today=today, actor_user_id=actor_user_id
            )
            return existing, False

        parent_id = uuid7()
        if await insert(row_id=parent_id, row_cell_id=None, is_group=True, parent_id=None):
            return parent_id, True

        # Another cell of this same block created the group between the read
        # and the write. The unique index is what makes that safe; the loser
        # simply joins the winner rather than opening a second card.
        found = await self._repo.find_open_group_parent(block_id=block_id, group_key=group_key)
        if found is not None:
            await self._repo.bump_recurrence(row_id=found, today=today, actor_user_id=actor_user_id)
        return found, False

    @property
    def repo(self) -> RecommendationsRepository:
        """Read-only handle for callers that need the lineage tables directly
        (the route that opens and closes an on-demand evaluation run)."""
        return self._repo

    # ---- Engine driver ------------------------------------------------

    async def evaluate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        tenant_id: UUID,
        run_id: UUID | None = None,
        only_tree_code: str | None = None,
        tally: dict[str, int] | None = None,
        excluded_by_farm: dict[UUID, frozenset[UUID]] | None = None,
        overrides_by_farm: dict[UUID | None, dict[UUID, dict[str, Any]]] | None = None,
    ) -> dict[str, int]:
        """Run every active tree visible to this tenant against
        ``block_id``; insert new open recommendations.

        ``only_tree_code`` narrows the pass to a single tree. Everything
        downstream - targeting, parameter overrides, dedup, traces, audit,
        notifications - is unchanged, which is the point: the authoring
        "run this tree now" button must produce the same rows the nightly
        sweep would, not a parallel implementation of them.

        ``tally``, when supplied, accumulates per-outcome counts
        (``fired`` / ``deduped`` / ``clear`` / ``error``) across every tree
        walked. ``deduped`` is the one the caller cannot infer: a tree that
        fired but hit the open-recommendation idempotency index opens
        nothing, and without this it is indistinguishable from a tree whose
        conditions simply did not match.

        ``tenant_id`` scopes the catalog lookup to platform trees +
        this tenant's own authored trees. The Beat task resolves this
        once per tenant before walking blocks (PR-A).

        ``run_id`` opts this evaluation into trace capture: every tree's
        verdict — including the ones that came out clear or were excluded by
        targeting — is recorded against that run. Omitted, nothing is written
        beyond the recommendations themselves, which keeps the many tests that
        drive this method directly from needing a run row.

        ``excluded_by_farm`` carries the tenant's farm-level tree selection
        so the sweep reads it once instead of once per block. Omitted, this
        block's farm is read on its own. ``overrides_by_farm`` is the same
        arrangement for the tree parameter overrides (tenant 0094).
        """
        setup = await self._prepare_block_evaluation(
            block_id=block_id,
            tenant_id=tenant_id,
            only_tree_code=only_tree_code,
            excluded_by_farm=excluded_by_farm,
            overrides_by_farm=overrides_by_farm,
        )
        if setup is None:
            return {
                "trees_evaluated": 0,
                "trees_skipped_crop": 0,
                "recommendations_opened": 0,
                "traces_written": 0,
                "verdicts_written": 0,
            }

        farm_id = setup.farm_id
        block_crop_id = setup.block_crop_id
        crop_path = setup.crop_path
        ctx = setup.ctx
        param_overrides_per_tree = setup.param_overrides_per_tree
        block_trees = setup.block_trees
        cell_trees = setup.cell_trees
        trees_skipped_crop = len(setup.skipped_trees)

        trees_evaluated = len(block_trees) + len(cell_trees)
        recommendations_opened = 0
        trace = _TraceBuffer(run_id=run_id) if run_id is not None else None
        # Unconditional, unlike the trace. A trace is lineage a caller can opt
        # into; a verdict is the answer itself, and a sweep that skipped it
        # would leave the map showing yesterday.
        verdicts = _VerdictBuffer(run_id=run_id)

        # Targeting exclusions first: these never reach the engine, so this is
        # the only place they can be recorded at all.
        if trace is not None:
            for tree, verdict in setup.skipped_trees:
                trace.add(
                    tree=tree,
                    farm_id=farm_id,
                    block_id=block_id,
                    cell_id=None,
                    status="skipped",
                    verdict=verdict,
                )

        # Block-scoped path.
        for tree in block_trees:
            overrides = param_overrides_per_tree.get(tree["tree_id"], {})
            outcome = await self._evaluate_and_record(
                tree=tree,
                eval_ctx=ctx,
                overrides=overrides,
                block_id=block_id,
                cell_id=None,
                farm_id=farm_id,
                block_crop_id=block_crop_id,
                crop_path=crop_path,
                actor_user_id=actor_user_id,
                tenant_schema=tenant_schema,
                trace=trace,
                verdicts=verdicts,
                tally=tally,
            )
            # A re-fire into a still-open item now returns a result instead of
            # None, because something WAS written — its recurrence counters.
            # Counting that as an opening would inflate every sweep's headline
            # number with work nobody has to look at.
            if outcome is not None and outcome.get("opened"):
                recommendations_opened += 1
        return await self._record_cell_scoped(
            setup=setup,
            block_id=block_id,
            actor_user_id=actor_user_id,
            tenant_schema=tenant_schema,
            trees_evaluated=trees_evaluated,
            trees_skipped_crop=trees_skipped_crop,
            recommendations_opened=recommendations_opened,
            trace=trace,
            verdicts=verdicts,
            # A run cut to one tree must not close the other trees' verdicts:
            # they were never walked, so their answers still stand.
            covers_every_tree=only_tree_code is None,
            tally=tally,
        )

    async def run_tree_on_farm(
        self,
        *,
        tree_code: str,
        farm_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        """Run one published tree across one farm, for real.

        This is the authoring counterpart to ``:dry-run``. The dry-run
        answers "what would this tree decide here?"; this answers "decide it
        and put the work in front of the team." Every block of the farm goes
        through the same ``evaluate_block`` the nightly sweep drives, with
        the tree set cut to one — so what lands in the Action Center is
        indistinguishable in kind from what the sweep produces, including
        traces, audit rows and notifications.

        Deliberately refuses to run an unpublished draft. A recommendation
        names the ``(tree_code, tree_version)`` that produced it and the
        Action Center links back to that version; a run from unsaved YAML
        would write rows nothing can explain afterwards. Test drafts with
        ``:dry-run``, publish, then run.

        Re-running is safe and expected: the partial UNIQUE on
        ``(block_id, tree_id) WHERE state='open'`` means a block that
        already carries an open recommendation from this tree gets no
        second one. The returned ``deduped`` count is what tells the author
        that happened, rather than leaving "0 opened" to read as failure.
        """
        if not await self._repo.farm_exists(farm_id=farm_id):
            raise FarmNotFoundError(farm_id)
        # The same visibility + published-version filter the sweep applies.
        # Empty here means the sweep would skip this tree too, so refusing is
        # the honest answer — see DecisionTreeNotRunnableError.
        trees = await self._repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id, only_code=tree_code
        )
        if not trees:
            raise DecisionTreeNotRunnableError(tree_code)
        tree = trees[0]

        block_ids = await self._repo.list_active_block_ids(farm_id=farm_id)
        labels = await self._repo.get_block_labels(block_ids=block_ids)

        # Traced like the sweep and the single-block debug run: an on-demand
        # pass that wrote recommendations but left no lineage would be the one
        # kind of run nobody could audit afterwards.
        run_id = await self._repo.open_eval_run(kind="on_demand", actor_user_id=actor_user_id)
        # Every alert this run opens holds its per-user channels back until
        # the run is announced finished, so the announcement has to happen
        # on the failure path too or those messages are never sent.
        announced = False

        def _announce_run_finished() -> None:
            nonlocal announced
            if announced:
                return
            announced = True
            self._bus.publish(
                EvaluationRunFinishedV1(
                    run_id=run_id, tenant_schema=tenant_schema, kind="on_demand"
                )
            )

        blocks: list[dict[str, Any]] = []
        totals = {
            "trees_evaluated": 0,
            "trees_skipped_targeting": 0,
            "recommendations_opened": 0,
            "traces_written": 0,
        }
        outcomes = {"fired": 0, "deduped": 0, "clear": 0, "error": 0}

        for block_id in block_ids:
            tally: dict[str, int] = {}
            summary = await self.evaluate_block(
                block_id=block_id,
                actor_user_id=actor_user_id,
                tenant_schema=tenant_schema,
                tenant_id=tenant_id,
                run_id=run_id,
                only_tree_code=tree_code,
                tally=tally,
            )
            totals["trees_evaluated"] += summary["trees_evaluated"]
            totals["trees_skipped_targeting"] += summary["trees_skipped_crop"]
            totals["recommendations_opened"] += summary["recommendations_opened"]
            totals["traces_written"] += summary.get("traces_written", 0)
            for key in outcomes:
                outcomes[key] += tally.get(key, 0)
            blocks.append(
                {
                    "block_id": block_id,
                    "label": labels.get(block_id, (str(block_id), None))[0],
                    "label_ar": labels.get(block_id, (str(block_id), None))[1],
                    # Zero when targeting excluded the tree from this block —
                    # the block was visited, the tree never walked.
                    "trees_evaluated": summary["trees_evaluated"],
                    "skipped_targeting": summary["trees_skipped_crop"] > 0,
                    "recommendations_opened": summary["recommendations_opened"],
                    "fired": tally.get("fired", 0),
                    "deduped": tally.get("deduped", 0),
                    "errors": tally.get("error", 0),
                }
            )

        await self._repo.close_eval_run(
            run_id=run_id,
            blocks_evaluated=len(block_ids),
            trees_evaluated=totals["trees_evaluated"],
            trees_skipped=totals["trees_skipped_targeting"],
            recommendations_opened=totals["recommendations_opened"],
            # Leaf-opened alerts are counted in the trace rows, not in the
            # per-block summary — same accounting as the sweep and the
            # single-block on-demand route.
            alerts_opened=0,
            traces_written=totals["traces_written"],
            # 'failed', not 'error' — the run row's CHECK constraint admits
            # only 'ok' | 'failed' (tenant 0062), and the trace rows are where
            # the per-tree 'error' status lives.
            outcome="failed" if outcomes["error"] else "ok",
        )
        _announce_run_finished()

        self._log.info(
            "decision_tree_farm_run",
            tree_code=tree_code,
            tree_version=tree["version"],
            farm_id=str(farm_id),
            run_id=str(run_id),
            blocks_evaluated=len(block_ids),
            recommendations_opened=totals["recommendations_opened"],
            deduped=outcomes["deduped"],
        )
        return {
            "run_id": run_id,
            "farm_id": farm_id,
            "tree_code": tree_code,
            "tree_version": tree["version"],
            "scope": tree.get("scope") or "block",
            "blocks_evaluated": len(block_ids),
            "blocks_targeted": sum(1 for b in blocks if not b["skipped_targeting"]),
            "recommendations_opened": totals["recommendations_opened"],
            "deduped": outcomes["deduped"],
            "cleared": outcomes["clear"],
            "errors": outcomes["error"],
            "traces_written": totals["traces_written"],
            "blocks": blocks,
        }

    # ---- Farm-level tree selection (tenant 0089) ----------------------

    async def list_farm_tree_selection(
        self, *, farm_id: UUID, tenant_id: UUID
    ) -> tuple[dict[str, Any], ...]:
        """Every tree this tenant can see, with whether the farm runs it.

        The list is the same catalog the sweep walks, so a farm manager sees
        exactly the trees that can reach their blocks. ``enabled`` is False
        only for a tree the farm turned off; targeting (crop, country, soil)
        is not applied here, because a tree that no block currently matches
        may match tomorrow when a crop is assigned.
        """
        if not await self._repo.farm_exists(farm_id=farm_id):
            raise FarmNotFoundError(farm_id)
        trees = await self._repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id
        )
        excluded = await self._repo.list_farm_tree_exclusions(farm_id=farm_id)
        return tuple(
            {
                "tree_id": tree["tree_id"],
                "code": tree["tree_code"],
                "name_en": tree["name_en"],
                "name_ar": tree["name_ar"],
                "scope": tree.get("scope") or "block",
                "version": tree["version"],
                # Where the tree came from. A tenant can turn off either kind.
                "source": "tenant" if tree["tenant_id"] is not None else "platform",
                "crop_paths": list(tree["crop_paths"] or []),
                "enabled": tree["tree_id"] not in excluded,
            }
            for tree in trees
        )

    async def set_farm_tree_enabled(
        self,
        *,
        farm_id: UUID,
        tree_id: UUID,
        tenant_id: UUID,
        enabled: bool,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Turn one tree on or off for one farm.

        Turning a tree off stops the next sweep from evaluating it for this
        farm's blocks. It leaves the recommendations and alerts the tree
        already opened exactly where they are: they describe something that
        was true in the field, and closing them would erase work a person
        still has to answer for.
        """
        if not await self._repo.farm_exists(farm_id=farm_id):
            raise FarmNotFoundError(farm_id)
        visible = await self._repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id
        )
        tree = next((t for t in visible if t["tree_id"] == tree_id), None)
        if tree is None:
            # Same 404 an unknown code gets. A tree another tenant authored
            # is invisible here, so it cannot be turned off by guessing an id.
            raise DecisionTreeNotFoundError(str(tree_id))

        if enabled:
            changed = await self._repo.remove_farm_tree_exclusion(farm_id=farm_id, tree_id=tree_id)
        else:
            changed = await self._repo.add_farm_tree_exclusion(
                farm_id=farm_id, tree_id=tree_id, actor_user_id=actor_user_id
            )

        if changed:
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type=(
                    "recommendations.farm_tree_enabled"
                    if enabled
                    else "recommendations.farm_tree_disabled"
                ),
                actor_user_id=actor_user_id,
                actor_kind="system" if actor_user_id is None else "user",
                subject_kind="decision_tree",
                subject_id=tree_id,
                farm_id=farm_id,
                details={"tree_code": tree["tree_code"], "enabled": enabled},
            )
        return {
            "tree_id": tree_id,
            "code": tree["tree_code"],
            "enabled": enabled,
            "changed": changed,
        }

    async def _prepare_block_evaluation(
        self,
        *,
        block_id: UUID,
        tenant_id: UUID,
        only_tree_code: str | None = None,
        excluded_by_farm: dict[UUID, frozenset[UUID]] | None = None,
        overrides_by_farm: dict[UUID | None, dict[UUID, dict[str, Any]]] | None = None,
    ) -> _BlockEvaluation | None:
        """Load the trees, signals and targeting split for ``block_id``.

        Returns ``None`` when the block has no parent farm (nothing can be
        evaluated). Performs no writes, so both the sweep and the read-only
        explain endpoint can call it.

        ``only_tree_code`` cuts the tree set to one before targeting is
        evaluated, so a single-tree run also skips the parameter-override
        bulk load for every other tree.

        ``excluded_by_farm`` is the tenant's farm-level tree selection, keyed
        by farm (tenant migration 0089). The sweep loads it once and passes
        it in, because this method runs once per block and the answer is the
        same for every block of one farm. A caller that omits it gets that
        one farm's rows read here, so a single-block caller stays correct
        without knowing about the table.

        ``overrides_by_farm`` is the parameter overrides read the same way,
        keyed by farm and then by tree, with the tenant-level rows under the
        key None (tenant 0094). Omitted, one query below reads both layers
        for this block's farm.
        """
        trees = await self._repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id, only_code=only_tree_code
        )
        latest = await self._repo.get_latest_aggregate_per_index(block_id=block_id)
        # Merge precomputed trend features (slope/delta/trend_direction)
        # into each index row so conditions can express "NDMI decreasing"
        # (KB P2). Indices without enough history are simply left without
        # trend fields → trend predicates fail closed.
        _merge_index_trends(latest, await self._repo.get_index_trends(block_id=block_id))
        farm_id = await self._repo.get_block_farm_id(block_id=block_id)
        (
            block_crop_id,
            crop_id,
            growth_stage,
            crop_path,
        ) = await self._repo.get_block_current_crop(block_id=block_id)
        soil_texture, salinity_class = await self._repo.get_block_soil(block_id=block_id)

        if farm_id is None:
            self._log.info("recommendations_skip_no_farm", block_id=str(block_id))
            return None

        # Country axis for targeting — inherited from the parent farm (PR-3).
        country_code = await self._repo.get_farm_country_code(farm_id=farm_id)

        # Trees this farm has turned off (tenant 0089).
        if excluded_by_farm is not None:
            excluded_trees = excluded_by_farm.get(farm_id, frozenset())
        else:
            excluded_trees = await self._repo.list_farm_tree_exclusions(farm_id=farm_id)

        # Pull weather + signals once per evaluation pass. Both loaders
        # return empty data when the block has no provider/observation
        # rows yet, so predicates fail closed instead of spuriously firing.
        weather = await load_weather_snapshot(self._tenant, farm_id=farm_id)
        weather_indices = await load_weather_index_snapshot(self._tenant, farm_id=farm_id)
        # Per-block disease/pest risk scores (PR-R3); empty until the daily
        # risk sweep scores this block, so `{source: weather_risk}` fails closed.
        weather_risks = await load_weather_risk_snapshot(self._tenant, block_id=block_id)
        water_balance = await load_water_balance_snapshot(self._tenant, block_id=block_id)
        signals = await load_signals_snapshot(self._tenant, block_id=block_id, farm_id=farm_id)
        # Sub-block grid spatial-anomaly verdicts (G-4). Empty for blocks
        # with no grid / no current anomaly, so `{source: grid}` predicates
        # fail closed just like every other source.
        grid = await load_grid_snapshot(
            self._tenant,
            self._public,
            block_id=block_id,
            tenant_id=tenant_id,
        )
        # Platform-curated crop attributes on the block's current assignment
        # (establishment method, transplant date, age at transplant, …).
        # Empty for a block with no assignment or no recorded values, so
        # `{source: crop_attribute}` predicates fail closed.
        crop_attributes = await load_crop_attribute_snapshot(
            self._tenant, block_crop_id=block_crop_id
        )
        ctx = ConditionContext.from_block_signals(
            block_id=str(block_id),
            block_attributes={
                "growth_stage": growth_stage,
                "soil_texture": soil_texture,
                "salinity_class": salinity_class,
            },
            latest_index_aggregates=latest,
            weather=weather,
            weather_indices=weather_indices,
            weather_risks=weather_risks,
            water_balance=water_balance,
            signals=signals,
            grid=grid,
            crop_attributes=crop_attributes,
        )

        # PR-C: bulk-load the parameter overrides for every tree the sweep
        # will walk. One query, grouped by tree_id; the engine falls back to
        # declared defaults for trees with no overrides.
        #
        # Three layers now resolve here, in this order (tenant 0094, design
        # 6.4): the tree's declared default, which the engine applies; the
        # tenant row; and this farm's own row on top of it. Whichever way the
        # rows arrive, they are read once — either from the sweep's single
        # pass over the table, or in one query for this farm.
        tree_ids = tuple(t["tree_id"] for t in trees)
        if overrides_by_farm is not None:
            tenant_layer = overrides_by_farm.get(None, {})
            farm_layer = overrides_by_farm.get(farm_id, {})
            param_overrides_per_tree = {
                tid: {**tenant_layer.get(tid, {}), **farm_layer.get(tid, {})} for tid in tree_ids
            }
        else:
            param_overrides_per_tree = await self._repo.list_all_param_overrides_visible_to_tenant(
                tree_ids=tree_ids, farm_id=farm_id
            )

        # Split matched trees by execution scope (PR-C3). Block-scoped trees
        # evaluate once against the block context; cell-scoped trees fan out
        # over the block's grid cells (cell imagery, inherit everything else).
        block_trees: list[dict[str, Any]] = []
        cell_trees: list[dict[str, Any]] = []
        skipped_trees: list[tuple[dict[str, Any], TargetingVerdict]] = []
        for tree in trees:
            # Farm-level selection (0089) is checked before targeting so the
            # trace says the farm turned this tree off, instead of naming a
            # crop or country axis that had nothing to do with the decision.
            if tree["tree_id"] in excluded_trees:
                skipped_trees.append((tree, _FARM_DISABLED))
                continue
            # Multi-axis targeting (PR-3): a tree fires on this block only if
            # its crop / country / soil sets all admit the block (AND across
            # axes, OR within; empty set = matches any). See evaluate_targeting.
            verdict = evaluate_targeting(
                tree,
                crop_path=crop_path,
                crop_id=crop_id,
                country_code=country_code,
                soil_texture=soil_texture,
            )
            if not verdict.matched:
                skipped_trees.append((tree, verdict))
                continue
            (cell_trees if tree.get("scope") == "cell" else block_trees).append(tree)

        return _BlockEvaluation(
            farm_id=farm_id,
            block_crop_id=block_crop_id,
            crop_path=crop_path,
            growth_stage=growth_stage,
            soil_texture=soil_texture,
            salinity_class=salinity_class,
            latest=latest,
            weather=weather,
            weather_indices=weather_indices,
            weather_risks=weather_risks,
            water_balance=water_balance,
            signals=signals,
            grid=grid,
            crop_attributes=crop_attributes,
            ctx=ctx,
            block_trees=block_trees,
            cell_trees=cell_trees,
            skipped_trees=skipped_trees,
            param_overrides_per_tree=param_overrides_per_tree,
        )

    async def _record_cell_scoped(
        self,
        *,
        setup: _BlockEvaluation,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        trees_evaluated: int,
        trees_skipped_crop: int,
        recommendations_opened: int,
        trace: _TraceBuffer | None = None,
        verdicts: _VerdictBuffer | None = None,
        covers_every_tree: bool = True,
        tally: dict[str, int] | None = None,
    ) -> dict[str, int]:
        """Run the cell-scoped trees and emit their digest notifications."""
        # Cached on the service, so this is a dict lookup after the first call
        # in a sweep. Needed here as well as in the per-firing path because the
        # end-of-sweep recount rolls the day-over-day baseline.
        today = await self._today(tenant_schema)
        farm_id = setup.farm_id
        block_crop_id = setup.block_crop_id
        crop_path = setup.crop_path
        cell_trees = setup.cell_trees
        param_overrides_per_tree = setup.param_overrides_per_tree

        # Cell-scoped path (PR-C3): one evaluation per grid cell, with the
        # cell's own imagery means swapped into an otherwise block-level
        # context. Empty when the block has no grid, so cell trees no-op there.
        #
        # Every firing cell now attaches to a group parent (0079) instead of
        # standing on the board in its own right. Two things therefore have to
        # be tracked across the whole sweep rather than per cell:
        #
        #   `fired_members` — which child rows fired this pass, per tree, so
        #   the ones that did NOT can be marked cleared afterwards. That
        #   bookkeeping cannot happen inside the loop: the interesting case is
        #   a cell the loop never reaches because the tree went quiet there.
        #
        #   `new_groups`    — the parents this pass created, so each can be
        #   announced exactly once with its final member count.
        fired_members: dict[UUID, list[UUID]] = {t["tree_id"]: [] for t in cell_trees}
        new_groups: dict[UUID, dict[str, Any]] = {}
        if cell_trees:
            cell_aggs = await self._repo.get_latest_cell_aggregates(block_id=block_id)
            for cid, cell_means in cell_aggs.items():
                cell_ctx = setup.cell_context(cell_means)
                for tree in cell_trees:
                    overrides = param_overrides_per_tree.get(tree["tree_id"], {})
                    opened = await self._evaluate_and_record(
                        tree=tree,
                        eval_ctx=cell_ctx,
                        overrides=overrides,
                        block_id=block_id,
                        cell_id=cid,
                        farm_id=farm_id,
                        block_crop_id=block_crop_id,
                        crop_path=crop_path,
                        actor_user_id=actor_user_id,
                        tenant_schema=tenant_schema,
                        trace=trace,
                        verdicts=verdicts,
                        tally=tally,
                    )
                    if opened is None:
                        continue
                    if opened.get("member_id") is not None:
                        fired_members[tree["tree_id"]].append(opened["member_id"])
                    if not opened.get("opened"):
                        # The cell fired into a group that already existed. Real
                        # work — it kept the group alive and refreshed this
                        # cell — but nothing new was opened, so it must not be
                        # counted as an opening or announced as one.
                        continue
                    recommendations_opened += 1
                    if opened["kind"] == "recommendation":
                        new_groups[opened["item_id"]] = {"tree": tree, "info": opened}

            # Cells that stopped firing, and the recount that follows. Run per
            # tree rather than per firing so a tree that fired nowhere today
            # still retires yesterday's members — the case a loop over results
            # cannot see at all.
            for tree in cell_trees:
                await self._repo.clear_stale_children(
                    block_id=block_id,
                    tree_id=tree["tree_id"],
                    fired_ids=fired_members[tree["tree_id"]],
                )
                await self._repo.refresh_member_counts_for_tree(
                    block_id=block_id, tree_id=tree["tree_id"], today=today
                )
                await self._alert_repo.clear_stale_children(
                    block_id=block_id,
                    tree_code=tree["tree_code"],
                    fired_ids=fired_members[tree["tree_id"]],
                )
                await self._alert_repo.refresh_member_counts_for_tree(
                    block_id=block_id, tree_code=tree["tree_code"], today=today
                )

        # One notification per group opened on this block. The group parent is
        # already block-level (cell_id=None) and already carries the count, so
        # this is no longer a synthetic digest standing in for N per-cell
        # events — it is the one event the one row deserves, published here
        # rather than at insert time because the member count is only final now.
        for parent_id, agg in new_groups.items():
            tree = agg["tree"]
            first = agg["info"]
            count = await self._repo.refresh_member_count(parent_id=parent_id, today=today) or 1
            self._bus.publish(
                RecommendationOpenedV1(
                    recommendation_id=parent_id,
                    block_id=block_id,
                    cell_id=None,
                    farm_id=farm_id,
                    tree_id=tree["tree_id"],
                    tree_code=tree["tree_code"],
                    tree_version=tree["version"],
                    action_type=first["action_type"],
                    severity=first["severity"],
                    confidence=Decimal("1.0"),
                    created_at=clock.now(),
                    tenant_schema=tenant_schema,
                    # Lead with what the tree concluded, not with the
                    # aggregation. "12 zones flagged" tells a supervisor how
                    # much, never what — and what is the part they act on.
                    text_en=(
                        first["text_en"]
                        if count <= 1
                        else f"{first['text_en']} — {count} zones affected in this block."
                    ),
                    text_ar=(
                        first.get("text_ar")
                        if count <= 1
                        else (
                            f"{first.get('text_ar') or first['text_en']} — "
                            f"{count} منطقة متأثرة في هذا الحقل."
                        )
                    ),
                    zone_count=count,
                    run_id=trace.run_id if trace is not None else None,
                    # No group_key here: `new_groups` records the tree and
                    # the opened row, not the key. The digest reads it off
                    # the recommendations row anyway, and a field that is
                    # always None is worse than one that is absent.
                )
            )

        # The verdicts for the whole block, written before the traces because
        # a verdict is an answer a user reads, not a record of the work.
        verdicts_written = 0
        if verdicts is not None:
            verdicts_written = await self._write_verdicts(
                verdicts=verdicts,
                block_id=block_id,
                cell_trees=cell_trees,
                covers_every_tree=covers_every_tree,
            )

        # One bulk insert for the whole block — see _TraceBuffer. Deliberately
        # last: a trace describes work that already happened, so a failure here
        # must not be able to roll back the recommendations it describes.
        traces_written = 0
        if trace is not None and trace.rows:
            traces_written = await self._repo.insert_eval_traces(rows=trace.rows)

        return {
            "trees_evaluated": trees_evaluated,
            "trees_skipped_crop": trees_skipped_crop,
            "recommendations_opened": recommendations_opened,
            "traces_written": traces_written,
            "verdicts_written": verdicts_written,
        }

    async def _write_verdicts(
        self,
        *,
        verdicts: _VerdictBuffer,
        block_id: UUID,
        cell_trees: list[dict[str, Any]],
        covers_every_tree: bool,
    ) -> int:
        """Store this block's verdicts and end the ones it no longer holds.

        One instant for the whole block. Reading the clock per statement would
        let an as-of read land between a close and the insert that replaces
        it, and report a block with no verdict at all for that microsecond.

        The two closing passes are the part a loop over the rows cannot do:

          * a tree that produced nothing — excluded by targeting, turned off
            for the farm, archived, or erroring — must not keep yesterday's
            answer open, or the block goes on claiming it was checked;
          * a cell the pass never reached, because the grid was rezoned or the
            tree stopped running there, holds a row nothing would touch again.

        Skipped entirely when the caller ran one tree instead of the whole
        set: the other trees were never walked, so their answers still stand.
        """
        at = clock.now()
        counts = await self._repo.sync_verdicts(rows=verdicts.rows, run_id=verdicts.run_id, at=at)
        if covers_every_tree:
            await self._repo.close_absent_verdicts(
                block_id=block_id, tree_ids=sorted(verdicts.seen_trees), at=at
            )
            for tree in cell_trees:
                await self._repo.close_stale_cell_verdicts(
                    block_id=block_id,
                    tree_id=tree["tree_id"],
                    seen_cell_ids=verdicts.seen_cells.get(tree["tree_id"], []),
                    at=at,
                )
        return int(counts["opened"]) + int(counts["confirmed"])

    # ---- Verdict reads (tenant 0091) ----------------------------------

    @staticmethod
    def status_catalog() -> list[dict[str, Any]]:
        """The five platform status codes, with rank, colour and both labels.

        Served rather than shipped in the frontend bundle. A frontend copy of
        a backend list has drifted before, and this one decides what colour a
        block is painted.
        """
        return [
            {
                "code": d.code,
                "rank": d.rank,
                "color": d.color,
                "label_en": d.label_en,
                "label_ar": d.label_ar,
            }
            for d in STATUS_DEFINITIONS
        ]

    async def block_verdicts(self, *, block_id: UUID, at: datetime | None = None) -> dict[str, Any]:
        """One block's verdicts, current or as of an instant."""
        rows = await self._repo.list_verdicts(block_id=block_id, at=_as_utc(at))
        return _block_group(block_id=block_id, rows=rows, as_of=at)

    async def farm_verdicts(self, *, farm_id: UUID, at: datetime | None = None) -> dict[str, Any]:
        """Every block of one farm, grouped, from a single statement.

        A block with no verdicts is absent from the list rather than present
        and empty: this read cannot tell "no tree ran here" from "this block
        does not exist", and inventing an entry would let a map paint a
        confident grey over the second case.
        """
        rows = await self._repo.list_verdicts(farm_id=farm_id, at=_as_utc(at))
        by_block: dict[UUID, list[dict[str, Any]]] = {}
        for row in rows:
            by_block.setdefault(row["block_id"], []).append(row)
        return {
            "farm_id": farm_id,
            "as_of": at,
            "blocks": [
                _block_group(block_id=block_id, rows=block_rows, as_of=at)
                for block_id, block_rows in by_block.items()
            ],
        }

    async def farm_verdict_history(
        self,
        *,
        farm_id: UUID,
        from_at: datetime,
        to_at: datetime,
        tree_code: str | None = None,
    ) -> dict[str, Any]:
        """Every verdict that stood at any point in the window, in one read.

        The map replays a range one calendar day at a time. Reading per day
        would be 30 requests for a month and 365 for a year, on a farm whose
        answer changes a handful of times in that period. This returns the
        intervals instead, and the client rebuilds each frame with the same
        test the SQL uses: `valid_from <= day AND (valid_to IS NULL OR
        valid_to > day)`.

        `truncated` is true when the guard cut the list. A caller that gets
        it has more history than a replay can draw and should narrow the
        window or name a tree, rather than draw a map that is quietly
        missing rows.
        """
        limit = _HISTORY_ROW_LIMIT
        rows = await self._repo.list_verdict_history(
            farm_id=farm_id,
            from_at=_as_utc(from_at) or from_at,
            to_at=_as_utc(to_at) or to_at,
            tree_code=tree_code,
            limit=limit + 1,
        )
        truncated = len(rows) > limit
        return {
            "farm_id": farm_id,
            "from_at": from_at,
            "to_at": to_at,
            "tree_code": tree_code,
            "truncated": truncated,
            "verdicts": rows[:limit],
        }

    async def verdict_reasoning(self, *, block_id: UUID, verdict_id: UUID) -> dict[str, Any] | None:
        """The walk behind one verdict, for the audience that reads verdicts.

        The trace endpoints under ``/decision-tree-traces`` answer the same
        question for a tree author, and they are gated on
        ``decision_tree.read``. Five roles hold ``recommendation.read`` and
        not that one — FarmManager, Agronomist, FieldOperator, Scout and
        Viewer — so every reader of the map would get a silent 403 on the
        one request that says why a cell is red. Hence a second door, gated
        the way the verdict reads are.

        ``reasoning_available`` is false when the run behind the verdict has
        been pruned by retention. The verdict is still correct; only the walk
        is gone, and the caller can say so instead of showing an empty list.
        """
        row = await self._repo.get_verdict_reasoning(block_id=block_id, verdict_id=verdict_id)
        if row is None:
            return None
        row["reasoning_available"] = row.get("trace_id") is not None
        row["node_path"] = row.get("node_path") or []
        row["resolved_values"] = row.get("resolved_values") or {}
        row["param_overrides"] = row.get("param_overrides") or {}
        # The leaf's own label, so the card can name the answer instead of
        # printing `leaf_dry_medium`. It is already in the walk — the leaf is
        # the step that carries no match, because it is the answer rather
        # than a check — and nothing was reading it.
        leaf_en, leaf_ar = _leaf_labels(row["node_path"])
        row["leaf_label_en"] = leaf_en
        row["leaf_label_ar"] = leaf_ar
        # The walk as prose, in both languages. Composed here rather than in
        # the browser so a report and a notification quote the same wording
        # as the screen; the step list rides along for the reader who wants
        # to audit a threshold.
        narrative = compose_both(
            status_code=str(row.get("status_code") or ""),
            tree_code=str(row.get("tree_code") or ""),
            tree_name_en=row.get("tree_name_en"),
            tree_name_ar=row.get("tree_name_ar"),
            text_en=row.get("text_en"),
            text_ar=row.get("text_ar"),
            node_path=row["node_path"],
            resolved_values=row["resolved_values"],
            evaluated_at=row.get("evaluated_at") or row.get("last_evaluated_at"),
            reasoning_available=bool(row["reasoning_available"]),
        )
        row["narrative_en"] = narrative["en"]
        row["narrative_ar"] = narrative["ar"]
        return row

    # ---- Read-only explain -------------------------------------------

    async def explain_block(
        self,
        *,
        block_id: UUID,
        tenant_id: UUID,
        farm_id: UUID,
    ) -> dict[str, Any]:
        """Walk every visible tree against ``block_id`` and report why each
        one did or didn't fire — **without writing anything**.

        This is the read model behind the Farm Console's Conditions tab.
        ``evaluate_block`` answers "what advice should exist"; this answers
        "show me the reasoning", including for trees that came out clear,
        which never leave a row in ``recommendations``.

        Cell-scoped trees are reported with ``status='per_cell'`` and no
        steps: they evaluate once per grid cell, so a single block-level
        verdict would be a lie. The console links those out to the per-cell
        popups instead.

        ``farm_id`` is the farm the caller was authorized against. The block
        is verified to belong to it — otherwise a user scoped to one farm
        could authorize with that farm and read a block from another.
        """
        setup = await self._prepare_block_evaluation(block_id=block_id, tenant_id=tenant_id)
        if setup is None:
            # No parent farm at all — indistinguishable from "not in your
            # farm" as far as the caller is concerned.
            raise BlockNotInFarmError(block_id=block_id, farm_id=farm_id)
        if setup.farm_id != farm_id:
            raise BlockNotInFarmError(block_id=block_id, farm_id=farm_id)

        trees: list[dict[str, Any]] = []

        for tree in setup.block_trees:
            overrides = setup.param_overrides_per_tree.get(tree["tree_id"], {})
            result = evaluate_tree(tree["tree_compiled"], setup.ctx, param_overrides=overrides)
            outcome = result.outcome
            fired = outcome is not None and outcome.action_type != "no_action"
            if result.error is not None:
                status = "error"
            elif fired:
                status = "fired"
            else:
                status = "clear"
            entry = _explain_entry(tree, status=status, steps=_explain_steps(tree, result))
            entry["error"] = result.error
            if outcome is not None:
                # The status code and the leaf's own words ride every walk
                # that reached a leaf, not only the ones that opened work.
                # "Clear" with no other detail was the screen equivalent of
                # the blank row this whole change exists to end.
                entry["status_code"] = outcome.status_code
                entry["kind"] = outcome.kind
                if not fired:
                    entry["text_en"] = outcome.text_en
                    entry["text_ar"] = outcome.text_ar
            if fired and outcome is not None:
                entry.update(
                    kind=outcome.kind,
                    action_type=outcome.action_type,
                    severity=outcome.severity,
                    confidence=float(outcome.confidence),
                    text_en=outcome.text_en,
                    text_ar=outcome.text_ar,
                )
            if outcome is not None:
                # The same paragraph the Farm Health card shows, composed by
                # the same module, so the two screens cannot describe one
                # block two ways. These steps carry the raw condition, which
                # the stored trace does not, so the thresholds here are the
                # tree's own rather than inferred from its parameters.
                narrative = compose_both(
                    status_code=outcome.status_code,
                    tree_code=str(tree["tree_code"]),
                    tree_name_en=tree.get("name_en"),
                    tree_name_ar=tree.get("name_ar"),
                    text_en=outcome.text_en,
                    text_ar=outcome.text_ar,
                    node_path=entry.get("steps") or [],
                    resolved_values=result.evaluation_snapshot,
                    evaluated_at=clock.now(),
                )
                entry["narrative_en"] = narrative["en"]
                entry["narrative_ar"] = narrative["ar"]
            trees.append(entry)

        for tree in setup.cell_trees:
            trees.append(_explain_entry(tree, status="per_cell", steps=[]))

        for tree, verdict in setup.skipped_trees:
            entry = _explain_entry(tree, status="skipped", steps=[])
            # Name the axis that rejected it. Without this the console says
            # "skipped" and the reader has to diff the tree's targeting against
            # the block by hand — and cannot see at all that the value is unset.
            entry["skip_axis"] = verdict.axis
            entry["skip_required"] = list(verdict.required)
            entry["skip_actual"] = verdict.actual
            trees.append(entry)

        return {
            "block_id": str(block_id),
            "evaluated_at": clock.now(),
            "crop_path": setup.crop_path,
            "trees": trees,
        }

    async def _evaluate_and_record(  # noqa: PLR0911 - one return per outcome kind
        self,
        *,
        tree: dict[str, Any],
        eval_ctx: ConditionContext,
        overrides: dict[str, Any],
        block_id: UUID,
        cell_id: UUID | None,
        farm_id: UUID,
        block_crop_id: UUID | None,
        crop_path: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
        trace: _TraceBuffer | None = None,
        verdicts: _VerdictBuffer | None = None,
        tally: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        """Evaluate one tree against one context (block or cell) and persist its
        output. Returns ``{"kind", "action_type", "severity"}`` for the opened
        rec/alert, or ``None`` when nothing was opened. Shared by the
        block-scoped and cell-scoped (PR-C3) evaluation paths; ``cell_id`` is
        None for block-scoped output and the grid cell for cell-scoped.

        When ``trace`` is supplied every exit below appends exactly one row to
        it — including the three that return ``None``. Those are the whole
        point: "nothing was opened" is the state that leaves no other evidence
        anywhere in the system."""
        started = perf_counter()

        def _trace(
            status: str,
            *,
            outcome: dict[str, Any] | None = None,
            recommendation_id: UUID | None = None,
            alert_id: UUID | None = None,
        ) -> None:
            # Counted here rather than at each call site because this closure
            # is the one thing every exit below goes through exactly once -
            # including the two that return None after the tree fired.
            if tally is not None:
                key = "deduped" if (outcome or {}).get("deduped") else status
                tally[key] = tally.get(key, 0) + 1
            # Every walk that reached a leaf leaves a verdict, whether it
            # opened work or not. `error` is the one status that does not:
            # the tree produced no leaf, so it has nothing to say, and the
            # close-absent pass at the end of the block ends whatever it
            # said yesterday rather than leaving a stale answer standing.
            if verdicts is not None and result.outcome is not None and status != "error":
                verdicts.add(
                    tree=tree,
                    farm_id=farm_id,
                    block_id=block_id,
                    cell_id=cell_id,
                    outcome=result.outcome,
                    alert_id=alert_id,
                    recommendation_id=recommendation_id,
                )
            if trace is None:
                return
            trace.add(
                tree=tree,
                farm_id=farm_id,
                block_id=block_id,
                cell_id=cell_id,
                status=status,
                result=result,
                overrides=overrides,
                outcome=outcome,
                recommendation_id=recommendation_id,
                alert_id=alert_id,
                duration_ms=int((perf_counter() - started) * 1000),
                fold=_fold_trace_columns(walk, card),
            )

        # Which engine walks this tree is decided by the tree's own shape and
        # by nothing else — not by a flag, not by the caller. A compiled body
        # holding a `register` or a `stop` node folds; everything else takes
        # the leaf-returning walk unchanged. The compiler refuses a tree that
        # has both shapes, so the two cases cannot overlap.
        walk: FoldingWalkResult | None = None
        card: FoldedCard | None = None
        if _is_folding_shape(tree["tree_compiled"]):
            walk, card = await self._walk_and_fold(
                tree=tree, eval_ctx=eval_ctx, overrides=overrides
            )
            result = _folding_evaluation(walk, card)
        else:
            result = evaluate_tree(tree["tree_compiled"], eval_ctx, param_overrides=overrides)
        if result.error is not None:
            self._log.warning(
                "decision_tree_walk_error",
                tree_code=tree["tree_code"],
                block_id=str(block_id),
                cell_id=str(cell_id) if cell_id else None,
                error=result.error,
            )
            _trace("error")
            return None
        if result.outcome is None or result.outcome.action_type == "no_action":
            # A status leaf or a no-action leaf. No work item opens, but the
            # verdict written above says what the block is, and the trace now
            # carries the same code so the lineage page can show it. A bare
            # "clear" was the screen equivalent of the blank row this change
            # exists to end.
            _trace(
                "clear",
                outcome=(
                    {
                        "kind": result.outcome.kind,
                        "status_code": result.outcome.status_code,
                        "leaf_node_id": result.path[-1].node_id if result.path else None,
                        "text_en": result.outcome.text_en,
                    }
                    if result.outcome is not None
                    else None
                ),
            )
            return None

        leaf_outcome = {
            "kind": result.outcome.kind,
            "status_code": result.outcome.status_code,
            "action_type": result.outcome.action_type,
            "severity": result.outcome.severity,
            "confidence": str(result.outcome.confidence),
            # The last step of the walk is the leaf that produced this outcome.
            "leaf_node_id": result.path[-1].node_id if result.path else None,
        }

        # The aggregation identity of this finding (0079). Cell-scoped output
        # collapses onto it; block-scoped output uses it only as a label.
        #
        # For a folding tree the leaf is not the identity: almost every walk
        # ends at the same `stop` node, so grouping on it would put every cell
        # of a block in one pile whatever the trees found there. The finding
        # set is the identity instead — the same key the Action Center groups
        # on and the supersede check compares (design 5.1).
        group_key = build_group_key(
            tree_code=tree["tree_code"],
            leaf_node_id=(
                "findings:" + "+".join(card.identity)
                if card is not None
                else leaf_outcome["leaf_node_id"]
            ),
            action_type=result.outcome.action_type,
            severity=result.outcome.severity,
        )
        today = await self._today(tenant_schema)

        # PR-E: dispatch on leaf kind. "alert" leaves write to tenant.alerts;
        # "recommendation" leaves take the path below.
        if result.outcome.kind == "alert":
            opened = await self._open_alert_from_tree(
                block_id=block_id,
                cell_id=cell_id,
                farm_id=farm_id,
                tree=tree,
                result=result,
                group_key=group_key,
                today=today,
                actor_user_id=actor_user_id,
                tenant_schema=tenant_schema,
                # `trace` is created only when the caller opened a run
                # (see evaluate_block), so it is the run marker itself.
                run_id=trace.run_id if trace is not None else None,
            )
            if opened["item_id"] is None:
                _trace("fired", outcome={**leaf_outcome, "deduped": True})
                return None
            # `deduped` still means "this firing opened nothing new". It is no
            # longer the same as "nothing was written": the existing item's
            # recurrence counters just moved, which is the whole point.
            _trace(
                "fired",
                outcome=leaf_outcome if opened["created"] else {**leaf_outcome, "deduped": True},
                alert_id=opened["item_id"],
            )
            return {
                "kind": "alert",
                "opened": opened["created"],
                "item_id": opened["item_id"],
                "member_id": opened["member_id"],
                # Was the literal string "alert" — a placeholder from when the
                # alert row had nowhere to keep the leaf's verb. It does now.
                "action_type": result.outcome.action_type,
                "severity": result.outcome.severity,
            }

        # Supersede (design 5.6). A folding tree writes one card per cell, so
        # a changed finding set has to close the open card before the new one
        # can be inserted: the dedup index would otherwise refuse the insert
        # with no error and leave yesterday's words standing.
        notify = True
        if card is not None:
            _superseded_id, notify = await self._supersede_open_card(
                card=card,
                block_id=block_id,
                cell_id=cell_id,
                farm_id=farm_id,
                tree=tree,
                actor_user_id=actor_user_id,
            )

        written = await self._persist_recommendation(
            tree=tree,
            result=result,
            block_id=block_id,
            cell_id=cell_id,
            farm_id=farm_id,
            block_crop_id=block_crop_id,
            crop_path=crop_path,
            group_key=group_key,
            today=today,
            actor_user_id=actor_user_id,
            finding_set=list(card.identity) if card is not None else None,
        )
        if written is None:
            # Lost a race and the winner has since been closed. There is
            # nothing to attribute this firing to, and inventing a row would
            # duplicate whatever closed it; tomorrow's sweep opens it cleanly.
            _trace("fired", outcome={**leaf_outcome, "deduped": True})
            return None
        recommendation_id = written["item_id"]
        member_id = written["member_id"]
        created = written["created"]

        _trace(
            "fired",
            outcome=leaf_outcome if created else {**leaf_outcome, "deduped": True},
            recommendation_id=recommendation_id,
        )
        if not created:
            # Nothing new to announce. The notification went out when the item
            # opened and the scouting visit it raised is still on somebody's
            # phone; re-publishing would put a second card there for a finding
            # they are already looking at.
            return {
                "kind": "recommendation",
                "opened": False,
                "item_id": recommendation_id,
                "member_id": member_id,
                "recommendation_id": recommendation_id,
                "action_type": result.outcome.action_type,
                "severity": result.outcome.severity,
                "text_en": result.outcome.text_en,
                "text_ar": result.outcome.text_ar,
            }

        await self._repo.insert_history(
            recommendation_id=recommendation_id,
            block_id=block_id,
            # The row this history belongs to is the group parent, and a parent
            # spans cells rather than sitting in one.
            cell_id=None,
            farm_id=farm_id,
            from_state=None,
            to_state="open",
            actor_user_id=actor_user_id,
            details={
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "action_type": result.outcome.action_type,
            },
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="recommendations.recommendation_opened",
            actor_user_id=actor_user_id,
            actor_kind="system" if actor_user_id is None else "user",
            subject_kind="recommendation",
            subject_id=recommendation_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                "cell_id": str(cell_id) if cell_id else None,
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "action_type": result.outcome.action_type,
                "severity": result.outcome.severity,
            },
        )
        # `notify` is True for every old-style leaf and for a folding card
        # that gained a finding or rose in severity. A set that only lost a
        # finding opens a new card and says nothing: a shrinking set never
        # asks for more work (design 5.6).
        if cell_id is None and notify:
            self._bus.publish(
                RecommendationOpenedV1(
                    recommendation_id=recommendation_id,
                    block_id=block_id,
                    cell_id=None,
                    farm_id=farm_id,
                    tree_id=tree["tree_id"],
                    tree_code=tree["tree_code"],
                    tree_version=tree["version"],
                    action_type=result.outcome.action_type,
                    severity=result.outcome.severity,
                    confidence=result.outcome.confidence,
                    created_at=clock.now(),
                    tenant_schema=tenant_schema,
                    text_en=result.outcome.text_en,
                    text_ar=result.outcome.text_ar,
                    parameters=result.outcome.parameters,
                    evaluation_snapshot=result.evaluation_snapshot,
                    # Inside a run the per-user channels wait for the run
                    # to finish so they can be consolidated; outside one
                    # they go out now.
                    run_id=trace.run_id if trace is not None else None,
                    group_key=group_key,
                )
            )
        # A cell-scoped group announces itself once, at the end of the block's
        # sweep, when its member count is final — see _record_cell_scoped.
        # Publishing here would tell the farm "1 zone" about a group that is
        # about to have fourteen.
        return {
            "kind": "recommendation",
            "opened": True,
            "item_id": recommendation_id,
            "member_id": member_id,
            "recommendation_id": recommendation_id,
            "action_type": result.outcome.action_type,
            "severity": result.outcome.severity,
            "text_en": result.outcome.text_en,
            "text_ar": result.outcome.text_ar,
        }

    async def _persist_recommendation(
        self,
        *,
        tree: dict[str, Any],
        result: Any,
        block_id: UUID,
        cell_id: UUID | None,
        farm_id: UUID,
        block_crop_id: UUID | None,
        crop_path: str | None,
        group_key: str,
        today: date,
        actor_user_id: UUID | None,
        finding_set: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Write the rows one firing of a recommendation leaf implies.

        Returns ``{item_id, member_id, created}``:

        * ``item_id``  — the row a supervisor acts on. The group parent for a
          cell-scoped tree, the recommendation itself for a block-scoped one.
        * ``member_id`` — this cell's own row, or None when block-scoped.
        * ``created``  — False when the firing landed in something that was
          already open. That is a recurrence, not silence: the counters moved.

        None means a race left nothing to attach to — rare, and deliberately
        not papered over with a fresh row that would duplicate whatever the
        winner became.
        """
        valid_until: datetime | None = None
        if result.outcome.valid_for_hours is not None:
            valid_until = clock.now() + timedelta(hours=result.outcome.valid_for_hours)

        # Snapshot the block's crop path (+ cell id when cell-scoped) alongside
        # the evaluated signals so the recommendation stays self-describing.
        snapshot: dict[str, Any] = {**result.evaluation_snapshot, "crop_path": crop_path}
        if cell_id is not None:
            snapshot["cell_id"] = str(cell_id)

        async def _insert(
            *,
            row_id: UUID,
            row_cell_id: UUID | None,
            is_group: bool,
            parent_id: UUID | None,
        ) -> bool:
            return await self._repo.insert_recommendation(
                recommendation_id=row_id,
                block_id=block_id,
                cell_id=row_cell_id,
                farm_id=farm_id,
                tree_id=tree["tree_id"],
                tree_code=tree["tree_code"],
                tree_version=tree["version"],
                block_crop_id=block_crop_id,
                action_type=result.outcome.action_type,
                severity=result.outcome.severity,
                parameters=result.outcome.parameters,
                actions=result.outcome.actions,
                confidence=result.outcome.confidence,
                tree_path=_serialize_path(result.path),
                text_en=result.outcome.text_en,
                text_ar=result.outcome.text_ar,
                valid_until=valid_until,
                evaluation_snapshot=snapshot,
                actor_user_id=actor_user_id,
                group_key=group_key,
                group_parent_id=parent_id,
                is_group=is_group,
                today=today,
                finding_set=finding_set,
            )

        member_id: UUID | None = None
        if cell_id is None:
            # Block-scoped: the item is already its own unit, so there is no
            # parent to make. A refused insert is the recurrence case — the
            # same finding, still open, true again today.
            recommendation_id = uuid7()
            created = await _insert(
                row_id=recommendation_id, row_cell_id=None, is_group=False, parent_id=None
            )
            if not created:
                existing = await self._repo.find_open_recommendation(
                    block_id=block_id, tree_id=tree["tree_id"], cell_id=None
                )
                if existing is None:
                    # Lost the race and the winner has since been closed.
                    # Reported as None so the caller records the firing without
                    # inventing a row that would duplicate whatever closed it.
                    return None
                recommendation_id = existing
                await self._repo.bump_recurrence(
                    row_id=recommendation_id, today=today, actor_user_id=actor_user_id
                )
        else:
            # Cell-scoped: the parent is what the queue shows and what anybody
            # acts on. This cell becomes one of its members and is never listed
            # in its own right.
            parent_id, created = await self._ensure_rec_group_parent(
                block_id=block_id,
                group_key=group_key,
                today=today,
                actor_user_id=actor_user_id,
                insert=_insert,
            )
            if parent_id is None:
                return None
            recommendation_id = parent_id
            member_id = uuid7()
            if not await _insert(
                row_id=member_id, row_cell_id=cell_id, is_group=False, parent_id=parent_id
            ):
                # This cell already had an open row — from before the group
                # existed, or from yesterday. Re-point it at the parent and
                # refresh its evidence rather than leaving an orphan the queue
                # can no longer reach.
                member_id = await self._repo.find_open_recommendation(
                    block_id=block_id, tree_id=tree["tree_id"], cell_id=cell_id
                )
                if member_id is not None:
                    await self._repo.attach_child(
                        child_id=member_id,
                        parent_id=parent_id,
                        group_key=group_key,
                        tree_version=tree["version"],
                        text_en=result.outcome.text_en,
                        text_ar=result.outcome.text_ar,
                        evaluation_snapshot=snapshot,
                        today=today,
                        actor_user_id=actor_user_id,
                    )

        return {"item_id": recommendation_id, "member_id": member_id, "created": created}

    async def _open_alert_from_tree(
        self,
        *,
        block_id: UUID,
        cell_id: UUID | None = None,
        farm_id: UUID,
        tree: dict[str, Any],
        result: Any,
        group_key: str,
        today: date,
        actor_user_id: UUID | None,
        tenant_schema: str,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Open (or re-fire) an alert produced by a tree-leaf with ``kind: alert``.

        The ``rule_code`` is synthesised as ``tree:<tree_code>:<leaf_node_id>``
        — the shape the Action Center splits provenance out of, and the shape
        the partial UNIQUE on ``(block_id, rule_code)`` dedups on.

        Cell-scoped output no longer smuggles the cell id into the *listed*
        row's rule_code. The group parent holds the plain rule_code and is what
        the queue shows; the per-cell children keep the ``:cell:<uuid>`` suffix,
        which is what still gives each cell its own idempotency without putting
        each cell on the board.

        Returns ``{item_id, member_id, created}``. ``item_id`` is the row a
        supervisor acts on — the parent for a cell-scoped tree, the alert itself
        otherwise — and is None only when a race left nothing to attach to.
        ``created`` is False when this firing landed in an item that already
        existed, which is a recurrence and not silence.
        """
        from app.modules.alerts.events import AlertOpenedV1
        from app.modules.alerts.repository import AlertsRepository

        outcome = result.outcome
        rule_code = f"tree:{tree['tree_code']}:{_alert_rule_leaf(outcome)}"
        alert_repo = AlertsRepository(tenant_session=self._tenant, public_session=self._public)

        async def _insert(
            *,
            row_id: UUID,
            row_cell_id: UUID | None,
            row_rule_code: str,
            is_group: bool,
            parent_id: UUID | None,
        ) -> bool:
            return await alert_repo.insert_alert(
                alert_id=row_id,
                block_id=block_id,
                cell_id=row_cell_id,
                rule_code=row_rule_code,
                severity=outcome.severity,
                # The leaf picked a verb even on the alert branch; 0063 gave the
                # alert row somewhere to keep it so the Action Center can group
                # alerts by task type alongside recommendations.
                action_type=outcome.action_type,
                diagnosis_en=outcome.text_en,
                diagnosis_ar=outcome.text_ar,
                prescription_en=None,
                prescription_ar=None,
                prescription_activity_id=None,
                signal_snapshot=result.evaluation_snapshot,
                actor_user_id=actor_user_id,
                group_key=group_key,
                group_parent_id=parent_id,
                is_group=is_group,
                today=today,
            )

        member_id: UUID | None = None
        alert_id: UUID | None = None
        if cell_id is None:
            fresh_id = uuid7()
            created = await _insert(
                row_id=fresh_id,
                row_cell_id=None,
                row_rule_code=rule_code,
                is_group=False,
                parent_id=None,
            )
            alert_id = fresh_id if created else None
            if not created:
                alert_id = await alert_repo.find_open_alert(block_id=block_id, rule_code=rule_code)
                if alert_id is None:
                    return {"item_id": None, "member_id": None, "created": False}
                await alert_repo.bump_recurrence(
                    row_id=alert_id, today=today, actor_user_id=actor_user_id
                )
                # The dedup index has no severity in it, so this row may have
                # been opened by an older version of the same leaf at a
                # different one. Health reads severity; without this a block
                # whose leaf was republished as critical stays on Watch until
                # somebody resolves the alert by hand.
                await alert_repo.restate_from_leaf(
                    row_id=alert_id,
                    severity=outcome.severity,
                    group_key=group_key,
                    action_type=outcome.action_type,
                )
        else:
            alert_id = await alert_repo.find_open_group_parent(
                block_id=block_id, group_key=group_key
            )
            created = False
            if alert_id is not None:
                await alert_repo.bump_recurrence(
                    row_id=alert_id, today=today, actor_user_id=actor_user_id
                )
            else:
                candidate = uuid7()
                created = await _insert(
                    row_id=candidate,
                    row_cell_id=None,
                    row_rule_code=rule_code,
                    is_group=True,
                    parent_id=None,
                )
                if created:
                    alert_id = candidate
                else:
                    # Another cell of this block opened the group first.
                    alert_id = await alert_repo.find_open_group_parent(
                        block_id=block_id, group_key=group_key
                    )
                    if alert_id is None:
                        return {"item_id": None, "member_id": None, "created": False}
                    await alert_repo.bump_recurrence(
                        row_id=alert_id, today=today, actor_user_id=actor_user_id
                    )

            child_rule = f"{rule_code}:cell:{cell_id}"
            member_id = uuid7()
            if not await _insert(
                row_id=member_id,
                row_cell_id=cell_id,
                row_rule_code=child_rule,
                is_group=False,
                parent_id=alert_id,
            ):
                member_id = await alert_repo.find_open_alert(
                    block_id=block_id, rule_code=child_rule
                )
                if member_id is not None:
                    await alert_repo.attach_child(
                        child_id=member_id,
                        parent_id=alert_id,
                        group_key=group_key,
                        diagnosis_en=outcome.text_en,
                        diagnosis_ar=outcome.text_ar,
                        signal_snapshot=result.evaluation_snapshot,
                        today=today,
                        actor_user_id=actor_user_id,
                    )

        if not created:
            return {"item_id": alert_id, "member_id": member_id, "created": False}

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="alerts.alert_opened",
            actor_user_id=actor_user_id,
            actor_kind="system" if actor_user_id is None else "user",
            subject_kind="alert",
            subject_id=alert_id,
            farm_id=farm_id,
            details={
                "block_id": str(block_id),
                # The parent spans cells; the cell that happened to open it is
                # recorded on its own child row, not here.
                "cell_id": None,
                "rule_code": rule_code,
                "severity": outcome.severity,
                "action_type": outcome.action_type,
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "leaf_node_id": outcome.leaf_node_id or "leaf",
                "group_key": group_key,
                "is_group": cell_id is not None,
            },
        )
        self._bus.publish(
            AlertOpenedV1(
                alert_id=alert_id,
                block_id=block_id,
                cell_id=None,
                rule_code=rule_code,
                severity=outcome.severity,
                created_at=clock.now(),
                tenant_schema=tenant_schema,
                farm_id=farm_id,
                diagnosis_en=outcome.text_en,
                diagnosis_ar=outcome.text_ar,
                prescription_en=None,
                prescription_ar=None,
                signal_snapshot=result.evaluation_snapshot,
                # Inside a run the per-user channels wait for the run to
                # finish so they can be consolidated; outside one they go
                # out now, because nothing will flush them later.
                run_id=run_id,
                tree_code=tree["tree_code"],
                group_key=group_key,
            )
        )
        return {"item_id": alert_id, "member_id": member_id, "created": True}

    # ---- Tree parameter overrides (tenant) ----------------------------

    async def list_tree_param_overrides(self, *, code: str, tenant_id: UUID) -> dict[str, Any]:
        """Return ``{declarations: [...], overrides: {name: value}}`` for
        the named tree, so the UI can render every declared parameter
        with its default + current override side by side. The tree
        must be visible to ``tenant_id`` (platform OR own); otherwise
        returns ``None``-equivalent and the caller raises 404.

        PR-C: this is the read endpoint behind the "Customize tree"
        settings page.
        """
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            return {"found": False}
        declarations = await self._param_decls_for_current_version(tree)
        overrides = await self._repo.list_param_overrides_for_tree(tree_id=tree["id"])
        return {
            "found": True,
            "tree_id": tree["id"],
            "code": code,
            "declarations": declarations,
            "overrides": overrides,
        }

    async def upsert_tree_param_override(
        self,
        *,
        code: str,
        tenant_id: UUID,
        param_name: str,
        value: Any,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Set a single override. Validates that ``param_name`` is a
        declared parameter on the tree's current published version;
        rejects with a sentinel so the router can map to 404 / 400.

        Type-coerces ``value`` against the declared type so a string
        ``"-0.15"`` saved by a number-typed input becomes a numeric
        JSONB at storage time. Bad coercions raise a parse error the
        router maps to 400.
        """
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        decls = await self._param_decls_for_current_version(tree)
        if param_name not in decls:
            raise _ParamNameUnknownError(code=code, param_name=param_name)
        coerced = _coerce_override_value(value, declared=decls[param_name])
        await self._repo.upsert_param_override(
            tree_id=tree["id"],
            param_name=param_name,
            value=coerced,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.tree_param_override_set",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree["id"],
            farm_id=None,
            details={"code": code, "param_name": param_name},
        )
        return {"code": code, "param_name": param_name, "value": coerced}

    async def delete_tree_param_override(
        self,
        *,
        code: str,
        tenant_id: UUID,
        param_name: str,
        actor_user_id: UUID | None,
    ) -> bool:
        """Remove a single override so the tree falls back to its
        declared default. Returns True if a row was deleted."""
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        deleted = await self._repo.delete_param_override(tree_id=tree["id"], param_name=param_name)
        if deleted:
            await self._audit.record(
                tenant_schema=None,
                event_type="recommendations.tree_param_override_deleted",
                actor_user_id=actor_user_id,
                actor_kind="user" if actor_user_id else "system",
                subject_kind="decision_tree",
                subject_id=tree["id"],
                farm_id=None,
                details={"code": code, "param_name": param_name},
            )
        return deleted

    async def _param_decls_for_current_version(
        self, tree: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Read the `parameters:` declaration block off the tree's
        current published version. Returns ``{}`` when the tree has
        no published version yet (override CRUD still allowed but
        every name fails validation — keeps the editor's draft flow
        honest)."""
        version_id = tree.get("current_version_id")
        if version_id is None:
            return {}
        version = await self._repo.get_version(version_id)
        if version is None:
            return {}
        compiled = version.get("tree_compiled") or {}
        decls = compiled.get("parameters") or {}
        return decls if isinstance(decls, dict) else {}

    # ---- Reads --------------------------------------------------------

    async def list_recommendations(
        self,
        *,
        farm_id: UUID | None = None,
        block_id: UUID | None = None,
        state_filter: tuple[str, ...] = (),
        action_type_filter: tuple[str, ...] = (),
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_recommendations(
            farm_id=farm_id,
            block_id=block_id,
            state_filter=state_filter,
            action_type_filter=action_type_filter,
            limit=limit,
        )

    async def get_recommendation(self, *, recommendation_id: UUID) -> dict[str, Any] | None:
        return await self._repo.get_recommendation(recommendation_id=recommendation_id)

    # ---- Transitions --------------------------------------------------

    async def transition_recommendation(  # noqa: PLR0912 - state-machine transition handler
        self,
        *,
        recommendation_id: UUID,
        action: str,
        dismissal_reason: str | None,
        deferred_until: datetime | None,
        outcome_notes: str | None,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Run the action through the recommendation state machine.

        Allowed transitions:

          * ``apply``    from ``open`` or ``deferred`` → ``applied``
          * ``dismiss``  from ``open`` or ``deferred`` → ``dismissed``
          * ``defer``    from ``open`` → ``deferred`` (requires
            ``deferred_until``)

        Anything else raises ``InvalidRecommendationTransitionError`` (HTTP 409).
        """
        before = await self._repo.get_recommendation(recommendation_id=recommendation_id)
        if before is None:
            raise RecommendationNotFoundError(recommendation_id)
        if before.get("group_parent_id") is not None:
            # A member is one cell's evidence under a group, not a decision
            # anyone makes on its own. Applying it alone would leave the group
            # open with a hole in it, and the caller is almost certainly acting
            # on a stale id — so name the parent instead of half-obeying.
            raise GroupMemberNotActionableError(
                recommendation_id=recommendation_id, parent_id=before["group_parent_id"]
            )
        current = before["state"]

        if action == "apply":
            if current not in ("open", "deferred"):
                raise InvalidRecommendationTransitionError(current_state=current, action=action)
            new_state = "applied"
        elif action == "dismiss":
            if current not in ("open", "deferred"):
                raise InvalidRecommendationTransitionError(current_state=current, action=action)
            new_state = "dismissed"
        elif action == "defer":
            if current != "open":
                raise InvalidRecommendationTransitionError(current_state=current, action=action)
            if deferred_until is None:
                raise InvalidRecommendationTransitionError(
                    current_state=current, action="defer (missing deferred_until)"
                )
            new_state = "deferred"
        else:
            raise InvalidRecommendationTransitionError(current_state=current, action=action)

        await self._repo.transition_recommendation(
            recommendation_id=recommendation_id,
            new_state=new_state,
            actor_user_id=actor_user_id,
            dismissal_reason=dismissal_reason,
            deferred_until=deferred_until,
            outcome_notes=outcome_notes,
        )
        # The group is what was acted on, so its cells move with it. Leaving a
        # member open under an applied parent would keep that cell's dedup key
        # occupied and swallow the next genuine firing there.
        cascaded: tuple[UUID, ...] = ()
        if before.get("is_group"):
            cascaded = await self._repo.cascade_children(
                parent_id=recommendation_id,
                new_state=new_state,
                actor_user_id=actor_user_id,
                dismissal_reason=dismissal_reason,
                deferred_until=deferred_until,
                outcome_notes=outcome_notes,
            )
        after = await self._repo.get_recommendation(recommendation_id=recommendation_id)
        if after is None:
            raise RecommendationNotFoundError(recommendation_id)

        await self._repo.insert_history(
            recommendation_id=recommendation_id,
            block_id=before["block_id"],
            farm_id=before["farm_id"],
            from_state=current,
            to_state=new_state,
            actor_user_id=actor_user_id,
            details={
                "tree_code": before["tree_code"],
                "tree_version": before["tree_version"],
                "dismissal_reason": dismissal_reason,
                "deferred_until": deferred_until.isoformat() if deferred_until else None,
                "outcome_notes": outcome_notes,
                "cascaded_members": len(cascaded),
            },
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type=f"recommendations.recommendation_{new_state}",
            actor_user_id=actor_user_id,
            subject_kind="recommendation",
            subject_id=recommendation_id,
            farm_id=before["farm_id"],
            details={
                "block_id": str(before["block_id"]),
                "tree_code": before["tree_code"],
                "previous_state": current,
            },
        )

        if new_state == "applied":
            self._bus.publish(
                RecommendationAppliedV1(
                    recommendation_id=recommendation_id,
                    block_id=before["block_id"],
                    tree_code=before["tree_code"],
                    actor_user_id=actor_user_id,
                )
            )
        elif new_state == "dismissed":
            self._bus.publish(
                RecommendationDismissedV1(
                    recommendation_id=recommendation_id,
                    block_id=before["block_id"],
                    tree_code=before["tree_code"],
                    actor_user_id=actor_user_id,
                    dismissal_reason=dismissal_reason,
                )
            )
        elif new_state == "deferred":
            self._bus.publish(
                RecommendationDeferredV1(
                    recommendation_id=recommendation_id,
                    block_id=before["block_id"],
                    tree_code=before["tree_code"],
                    actor_user_id=actor_user_id,
                    deferred_until=deferred_until,
                )
            )
        return after


def _leaf_labels(node_path: Sequence[Any]) -> tuple[str | None, str | None]:
    """The label of the leaf a walk ended on, in both languages.

    A step carries ``matched`` True or False; the leaf carries None, because
    it is the answer rather than a check. Read from the end, so a malformed
    walk with an unmatched step in the middle cannot be mistaken for the
    conclusion.

    Returns ``(None, None)`` for a pruned or empty walk, and the caller keeps
    showing the node id — which is worse to read but is never wrong.
    """
    for step in reversed(list(node_path)):
        if not isinstance(step, Mapping) or step.get("matched") is not None:
            continue
        label_en = step.get("label_en")
        label_ar = step.get("label_ar")
        return (
            str(label_en) if label_en else None,
            str(label_ar) if label_ar else None,
        )
    return None, None


def _serialize_path(steps: list[TreePathStep]) -> list[dict[str, Any]]:
    """Flatten ``TreePathStep`` instances for JSONB storage on the
    recommendations row. Only fields the UI needs are kept."""
    out: list[dict[str, Any]] = []
    for step in steps:
        out.append(
            {
                "node_id": step.node_id,
                "matched": step.matched,
                "label_en": step.label_en,
                "label_ar": step.label_ar,
                "values": step.condition_snapshot or {},
            }
        )
    return out


def _dry_run_fired(result: EvaluationResult) -> bool:
    """A walk "matched" only if it reached a leaf that would open something —
    a ``no_action`` leaf is a verdict, not a match."""
    return result.outcome is not None and result.outcome.action_type != "no_action"


def _dry_run_outcome(result: EvaluationResult) -> dict[str, Any] | None:
    if result.outcome is None:
        return None
    return {
        # The kind and the status ride every dry run, not only the ones that
        # would open work. A status leaf has no action_type, and without
        # these two the panel had nothing to show for it — the author would
        # test a status branch and see a blank where the answer is.
        "kind": result.outcome.kind,
        "status_code": result.outcome.status_code,
        "action_type": result.outcome.action_type,
        "severity": result.outcome.severity,
        "confidence": str(result.outcome.confidence),
        "parameters": result.outcome.parameters,
        "text_en": result.outcome.text_en,
        "text_ar": result.outcome.text_ar,
        "valid_for_hours": result.outcome.valid_for_hours,
        "actions": result.outcome.actions,
    }


def _explain_entry(
    tree: dict[str, Any],
    *,
    status: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """One tree's row in the explain response, with the outcome fields
    nulled out. Callers overwrite them when the tree actually fired."""
    return {
        "tree_id": str(tree["tree_id"]),
        "code": tree["tree_code"],
        "name_en": tree.get("name_en"),
        "name_ar": tree.get("name_ar"),
        "version": tree.get("version"),
        "scope": tree.get("scope") or "block",
        "status": status,
        "steps": steps,
        "kind": None,
        "action_type": None,
        "severity": None,
        "confidence": None,
        "text_en": None,
        "text_ar": None,
        "error": None,
        # Only ever populated on a `skipped` row; see evaluate_targeting.
        "skip_axis": None,
        "skip_required": [],
        "skip_actual": None,
    }


def _explain_steps(tree: dict[str, Any], result: EvaluationResult) -> list[dict[str, Any]]:
    """Serialize a walk for the Conditions tab.

    ``_serialize_path`` (used for the JSONB snapshot on a recommendation
    row) carries the resolved left-hand values but not the predicate, so a
    reader can see "ndvi = 0.39" and not "…and the threshold was 0.45".
    Here we attach each decision node's raw condition tree as well, which
    is what lets the UI render the full "actual vs. threshold" line.
    """
    nodes = (tree.get("tree_compiled") or {}).get("nodes") or {}
    out: list[dict[str, Any]] = []
    for step in result.path:
        node = nodes.get(step.node_id) or {}
        # Leaf nodes carry an outcome rather than a condition; matched is
        # None there and the UI renders them as the verdict, not a check.
        condition = (node.get("condition") or {}).get("tree")
        out.append(
            {
                "node_id": step.node_id,
                "matched": step.matched,
                "label_en": step.label_en,
                "label_ar": step.label_ar,
                "values": step.condition_snapshot or {},
                "condition": condition,
            }
        )
    return out


def _merge_index_trends(
    latest: dict[str, dict[str, Any]],
    trends: dict[str, dict[str, Any]],
) -> None:
    """Fold trend features into the latest-aggregate rows in place (KB P2).

    Only indices that already have a latest aggregate are touched; a trend
    for an index with no current row is ignored (can't happen in practice
    — trends are a subset of the same hypertable)."""
    for code, trend in trends.items():
        if code in latest:
            latest[code].update(trend)


# Severity ordering for picking the worst across a cell-scoped tree's zones.
_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}


def _merge_cell_means(
    block_latest: dict[str, dict[str, Any]],
    cell_means: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a cell's ``indices`` context from the block's latest aggregates
    with the cell's own per-index ``mean`` swapped in (PR-C3, input fidelity:
    cell imagery, inherit the rest).

    ``baseline_deviation`` and trend features stay the block's — they're
    per-block z-scores with no per-cell equivalent in ``block_grid_aggregates``,
    so a cell predicate on ``{key: baseline_deviation}`` reads the block value
    while ``{key: mean}`` reads the cell's own mean. Indices the cell has no
    observation for keep the block's row unchanged."""
    merged: dict[str, dict[str, Any]] = {code: dict(vals) for code, vals in block_latest.items()}
    for code, cvals in cell_means.items():
        if code in merged:
            merged[code] = {**merged[code], "mean": cvals["mean"]}
        else:
            merged[code] = {
                "time": cvals["time"],
                "mean": cvals["mean"],
                "baseline_deviation": None,
            }
    return merged


@dataclass(frozen=True, slots=True)
class TargetingVerdict:
    """Why a tree was, or was not, admitted to a block.

    ``matched=False`` always names the ``axis`` that rejected it plus both
    sides of that comparison, so a trace can answer "the tree wanted EG and
    this farm has no country set" instead of the bare "skipped" the sweep
    used to record.
    """

    matched: bool
    axis: str | None = None
    # What the tree demanded on that axis. Empty when the axis is the legacy
    # single ``crop_id`` rather than a set.
    required: tuple[str, ...] = ()
    # What the block (or its farm, for country) actually had. None means the
    # value is unset — the common cause, and invisible before this existed.
    actual: str | None = None


_MATCHED = TargetingVerdict(matched=True)
# The farm turned this tree off. `axis="farm"` is one of the values the
# `skip_axis` CHECK on decision_tree_eval_traces accepts; tenant migration
# 0089 widened it to take this one.
_FARM_DISABLED = TargetingVerdict(
    matched=False, axis="farm", required=("enabled",), actual="disabled"
)


def evaluate_targeting(
    tree: dict[str, Any],
    *,
    crop_path: str | None,
    crop_id: UUID | None,
    country_code: str | None,
    soil_texture: str | None,
) -> TargetingVerdict:
    """``tree_targets_block`` with the rejection reason attached.

    Axis order is crop → country → soil. Since the axes are ANDed the order
    cannot change the verdict, only which axis gets reported first when more
    than one would reject; crop is reported first because it is the axis
    authors set most often and think about first.
    """
    crop_paths: list[str] = tree.get("crop_paths") or []
    if crop_paths:
        if not any(path_matches(p, crop_path) for p in crop_paths):
            return TargetingVerdict(
                matched=False,
                axis="crop",
                required=tuple(crop_paths),
                actual=crop_path,
            )
    else:
        legacy_crop_id = tree.get("crop_id")
        if legacy_crop_id is not None and legacy_crop_id != crop_id:
            return TargetingVerdict(
                matched=False,
                axis="crop",
                required=(str(legacy_crop_id),),
                actual=str(crop_id) if crop_id is not None else None,
            )

    country_codes: list[str] = tree.get("country_codes") or []
    if country_codes and (country_code is None or country_code not in country_codes):
        return TargetingVerdict(
            matched=False,
            axis="country",
            required=tuple(country_codes),
            actual=country_code,
        )

    soil_textures: list[str] = tree.get("soil_textures") or []
    if soil_textures and (soil_texture is None or soil_texture not in soil_textures):
        return TargetingVerdict(
            matched=False,
            axis="soil",
            required=tuple(soil_textures),
            actual=soil_texture,
        )

    return _MATCHED


def tree_targets_block(
    tree: dict[str, Any],
    *,
    crop_path: str | None,
    crop_id: UUID | None,
    country_code: str | None,
    soil_texture: str | None,
) -> bool:
    """Multi-axis targeting match (DT targeting PR-3).

    A tree matches a block iff **every** axis passes (AND across axes). An
    axis with an empty set matches any block; otherwise the block's value
    must be in the set (OR within an axis):

      * crop     — any of ``crop_paths`` prefix-matches the block's crop
                   path. Back-compat: when ``crop_paths`` is empty but the
                   legacy ``crop_id`` is set, fall back to the exact-crop
                   match; empty + no crop_id = crop-agnostic.
      * country  — block's farm country is one of ``country_codes``.
      * soil     — block's ``soil_texture`` is one of ``soil_textures``.

    A block whose value on a constrained axis is unknown (None) never
    matches that axis — e.g. a tree filtered by country won't fire on a
    farm with no country set. This is the coverage guardrail: country is
    net-new, so farms are backfilled to a country before such trees ship.

    Kept as the boolean face of ``evaluate_targeting`` for the callers that
    only need to filter (the dry-run block picker); the evaluation paths use
    the verdict so the rejected axis reaches the trace.
    """
    return evaluate_targeting(
        tree,
        crop_path=crop_path,
        crop_id=crop_id,
        country_code=country_code,
        soil_texture=soil_texture,
    ).matched


def get_recommendations_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> RecommendationsServiceImpl:
    return RecommendationsServiceImpl(tenant_session=tenant_session, public_session=public_session)


# Type-checker assist: the impl satisfies the Protocol.
def _check(impl: RecommendationsServiceImpl) -> RecommendationsService:
    return impl


# =====================================================================
# Decision-tree authoring service (PlatformAdmin)
# =====================================================================


class DecisionTreesAuthorService:
    """Author + manage decision-tree catalog rows.

    Lives on the same repository as the rest of the recommendations
    module — it just exposes a different slice of methods. Separated
    from ``RecommendationsServiceImpl`` so the authoring routes don't
    need a tenant session at all (the tree catalog is platform-scoped).

    Persistence shape:
      * Each save is a new ``decision_tree_versions`` row + an updated
        ``decision_trees.current_version_id`` when the caller asks to
        publish.
      * "Drafts" are versions with ``published_at IS NULL`` — the
        evaluator (`list_active_trees_with_current_version`) only picks
        published versions. So a draft is invisible to tenants until
        a separate publish call lands.
      * The YAML loader at startup is unaffected: it inserts a new
        version only when the on-disk hash differs from the latest
        version in the DB. Versions authored via this service simply
        push the latest hash forward; the next loader run will be a
        no-op if the on-disk YAML matches.
    """

    def __init__(self, *, public_session: AsyncSession, tenant_id: UUID | None) -> None:
        """``tenant_id`` is the caller's scope (from ``RequestContext``).

        A UUID scopes every read to platform PLUS this tenant, and stamps
        every authoring write with this tenant's UUID, so tenant-A's
        trees are never visible to or writable by tenant-B.

        ``None`` is the platform scope, held by a caller with a platform
        role and no tenant. It reads and writes only ``tenant_id IS NULL``
        rows — the platform catalogue. That used to have no writer at all:
        the YAML seed loader produced those rows and rewrote them at the
        next startup, so an edit made in the app did not survive a restart.
        Public migration 0085 moved the definitions into the database and
        the startup sync is gone, which is what makes this scope real.
        """
        self._public = public_session
        self._tenant_id = tenant_id
        self._repo = RecommendationsRepository(
            tenant_session=public_session,  # unused for authoring paths
            public_session=public_session,
        )
        self._audit = get_audit_service()
        self._log = get_logger(__name__)

    # ---- Reads --------------------------------------------------------

    async def list_trees(self) -> tuple[dict[str, Any], ...]:
        return await self._repo.list_all_trees(visible_to_tenant_id=self._tenant_id)

    async def get_tree_detail(self, *, code: str) -> dict[str, Any] | None:
        from app.modules.recommendations.repository import _serialize_jsonb  # noqa: F401

        # Reads see platform + own; that's how a tenant viewing a
        # platform tree's detail (e.g. to customize its parameters
        # in PR-C) hits the right row.
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=self._tenant_id, include_platform=True
        )
        if tree is None:
            return None
        versions = await self._repo.list_versions_for_tree(tree_id=tree["id"])
        # Surface the version *number* of the current published version
        # so the UI can highlight it.
        current_version_number: int | None = None
        if tree["current_version_id"] is not None:
            for v in versions:
                if v["id"] == tree["current_version_id"]:
                    current_version_number = v["version"]
                    break
        return {
            "id": tree["id"],
            "code": tree["code"],
            "tenant_id": tree["tenant_id"],
            "name_en": tree["name_en"],
            "name_ar": tree["name_ar"],
            "description_en": tree["description_en"],
            "description_ar": tree["description_ar"],
            "crop_id": tree["crop_id"],
            "crop_paths": tree["crop_paths"],
            "country_codes": tree["country_codes"],
            "soil_textures": tree["soil_textures"],
            "scope": tree["scope"],
            "applicable_regions": tree["applicable_regions"],
            "is_active": tree["is_active"],
            "current_version": current_version_number,
            "versions": [dict(v) for v in versions],
        }

    # ---- Writes -------------------------------------------------------

    async def _versions_to_check(self, tree: dict[str, Any]) -> list[dict[str, Any]]:
        """The compiled bodies a targeting change could invalidate: the
        published version (what runs now) and the newest one (what the author
        is about to publish). Usually the same row, so this returns one body;
        two when a draft is pending, none on a tree with no versions yet.
        """
        bodies: list[dict[str, Any]] = []
        seen: set[UUID] = set()
        current_id = tree.get("current_version_id")
        if current_id is not None:
            current = await self._repo.get_version(current_id)
            if current is not None:
                seen.add(current["id"])
                bodies.append(current.get("tree_compiled") or {})
        latest_number = await self._repo.get_latest_version_number(tree_id=tree["id"])
        if latest_number > 0:
            latest = await self._repo.get_version_by_number(
                tree_id=tree["id"], version=latest_number
            )
            if latest is not None and latest["id"] not in seen:
                bodies.append(latest.get("tree_compiled") or {})
        return bodies

    async def _assert_crop_attribute_refs_resolve(
        self,
        compiled: dict[str, Any],
        *,
        crop_paths: list[str] | None = None,
    ) -> None:
        """Reject a tree that branches on a crop attribute its target crops
        never define.

        `{source: crop_attribute}` is the one condition source whose valid
        codes are data rather than a constant, so `compile_tree` cannot check
        them: the catalog lives in `public.crop_attribute_definitions` and the
        valid subset depends on the tree's targeting. The result of skipping
        the check is a ref that resolves to None for every block the tree runs
        on — permissive-on-missing-data means the comparison fails closed
        forever and nothing anywhere reports it.

        Skipped when the tree targets no crop: with no targeting there is no
        subset to check against, and "matches any crop" would make every code
        in the catalog legal anyway. Create requires at least one path, so in
        practice this only spares trees seeded before targeting existed.
        """
        from app.modules.recommendations.loader import collect_crop_attribute_codes

        referenced = collect_crop_attribute_codes(compiled.get("nodes") or {})
        if not referenced:
            return
        paths = crop_paths if crop_paths is not None else list(compiled.get("crop_paths") or [])
        if not paths:
            return
        available = await self._repo.list_crop_attribute_codes_for_paths(paths=paths)
        unknown = sorted(referenced - available)
        if unknown:
            raise _DecisionTreeUnknownCropAttributeError(codes=unknown, crop_paths=paths)

    async def create_tree(
        self,
        *,
        code: str,
        crop_code: str | None,
        tree_yaml: str,
        crop_paths: list[str] | None = None,
        country_codes: list[str] | None = None,
        soil_textures: list[str] | None = None,
        scope: str | None = None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Create a new tree + its v1 draft. Validates the YAML via
        ``compile_tree`` before any DB write — a malformed body never
        produces a half-created row."""
        import yaml as _yaml

        from app.modules.recommendations.errors import DecisionTreeNotFoundError
        from app.modules.recommendations.loader import (
            _hash_compiled,
            compile_tree,
        )

        # Reject collisions both within the tenant's own scope and
        # against the platform catalog. Forbidding tenant codes that
        # shadow a platform code keeps lookups by `code` unambiguous
        # without needing an explicit "platform vs tenant" filter at
        # every read site.
        if (
            await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id) is not None
            or await self._repo.get_tree_by_code(code, scope_tenant_id=None) is not None
        ):
            raise _DecisionTreeCodeAlreadyExistsError(code)

        spec = _yaml.safe_load(tree_yaml)
        # Structured targeting from the authoring pickers (PR-5) overrides
        # whatever the YAML body declares, so the form is the source of truth
        # for crop/country/soil and the author needn't hand-edit the YAML.
        if isinstance(spec, dict):
            if crop_paths is not None:
                spec["crop_paths"] = crop_paths
            if country_codes is not None:
                spec["country_codes"] = country_codes
            if soil_textures is not None:
                spec["soil_textures"] = soil_textures
            if scope is not None:
                spec["scope"] = scope
        compiled = compile_tree(spec, source_path=f"<api:{code}>")
        # The compiled body's `code` field must match the URL — protect
        # against a typo where the YAML says one thing and the URL another.
        if compiled.get("code") != code:
            raise _DecisionTreeCodeMismatchError(expected=code, got=str(compiled.get("code")))
        await self._assert_crop_attribute_refs_resolve(compiled)
        compiled_hash = _hash_compiled(compiled)
        crop_path = compiled.get("crop_path")
        # crop_code from the request takes precedence; otherwise derive it
        # from the path's first segment so crop_id stays populated.
        crop_id = await self._repo.resolve_crop_id(
            crop_code or (crop_path.split(".")[0] if crop_path else None)
        )

        tree_id = await self._repo.insert_tree(
            code=code,
            tenant_id=self._tenant_id,
            name_en=compiled["name_en"],
            name_ar=compiled.get("name_ar"),
            description_en=compiled.get("description_en"),
            description_ar=compiled.get("description_ar"),
            crop_id=crop_id,
            crop_path=crop_path,
            crop_paths=compiled.get("crop_paths") or [],
            country_codes=compiled.get("country_codes") or [],
            soil_textures=compiled.get("soil_textures") or [],
            scope=compiled.get("scope") or "block",
            applicable_regions=compiled.get("applicable_regions") or [],
            actor_user_id=actor_user_id,
        )
        version_id = await self._repo.insert_version(
            tree_id=tree_id,
            version=1,
            tree_yaml=tree_yaml,
            tree_compiled=compiled,
            compiled_hash=compiled_hash,
            notes=None,
            published_at=None,
            published_by=None,
        )
        # Don't auto-publish on create — the editor explicitly publishes
        # via the separate endpoint so v1 starts as a draft like any
        # later version. (Alternative would be auto-publish-on-create
        # for ergonomics; the chosen behaviour matches the explicit
        # draft → publish flow we tell users about.)
        del version_id
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_created",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree_id,
            farm_id=None,
            details={"code": code, "version": 1},
        )
        # Re-read so the caller sees the same shape as get_tree_detail.
        tree = await self.get_tree_detail(code=code)
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        # Silence unused-import noise.
        del DecisionTreeNotFoundError
        return tree

    async def _own_tree_or_raise(self, code: str) -> dict[str, Any]:
        """The caller's own tree with this code, or the reason there is none.

        Every authoring write scopes to the caller's own rows. A tenant writes
        rows carrying its own `tenant_id`; a platform admin writes rows with
        `tenant_id IS NULL`. Neither reaches the other's, and this is the
        tenant half of that.

        The scoped lookup cannot tell "no such tree" from "not yours", and it
        used to report both as missing. A 404 saying "No decision tree with
        code 'mango_canopy_vigour_by_size_v1'" about a tree the author has
        open on screen sends somebody hunting a data problem that is not
        there. So the second lookup runs only on the failure path, and only
        to name what actually happened.
        """
        tree = await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id)
        if tree is not None:
            return tree
        if self._tenant_id is not None:
            platform = await self._repo.get_tree_by_code(code, scope_tenant_id=None)
            if platform is not None:
                raise _PlatformTreeNotEditableError(code)
        raise _DecisionTreeNotFoundError(code)

    async def append_version(
        self,
        *,
        code: str,
        tree_yaml: str,
        notes: str | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        import yaml as _yaml

        from app.modules.recommendations.loader import (
            _hash_compiled,
            compile_tree,
        )

        # Writes scope strictly to the caller's own tenant — a tenant
        # cannot author a new version of a platform tree (those are
        # YAML-managed). Platform-tree customization in PR-C goes
        # through a separate override path, not version-append.
        tree = await self._own_tree_or_raise(code)
        spec = _yaml.safe_load(tree_yaml)
        compiled = compile_tree(spec, source_path=f"<api:{code}>")
        if compiled.get("code") != code:
            raise _DecisionTreeCodeMismatchError(expected=code, got=str(compiled.get("code")))
        # Targeting is not in the version payload — it lives on the tree row
        # and the pickers edit it separately, so check against the stored set.
        await self._assert_crop_attribute_refs_resolve(
            compiled, crop_paths=list(tree.get("crop_paths") or [])
        )
        compiled_hash = _hash_compiled(compiled)
        # No-op when the new YAML hashes identical — the editor can
        # call save liberally; we only insert when there's actually a
        # change.
        latest = await self._repo.get_latest_version_number(tree_id=tree["id"])
        if latest > 0:
            latest_row = await self._repo.get_version_by_number(tree_id=tree["id"], version=latest)
            if latest_row is not None and latest_row["compiled_hash"] == compiled_hash:
                return await self._tree_with_version(code=code, version=latest)
        next_version = latest + 1
        version_id = await self._repo.insert_version(
            tree_id=tree["id"],
            version=next_version,
            tree_yaml=tree_yaml,
            tree_compiled=compiled,
            compiled_hash=compiled_hash,
            notes=notes,
            published_at=None,
            published_by=None,
        )
        # The tree row's name and description are NOT touched here.
        #
        # They used to be, so the catalogue would "reflect what the author
        # last saved". But a draft is meant to be invisible until published —
        # that is the whole point of the draft state, and the evaluator
        # honours it. The name and description did not: saving a draft
        # renamed the tree in the catalogue and in every reader's page header
        # while the engine still walked the published version.
        #
        # They are stamped at publish instead, from the version being
        # published. See `publish_version`.
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_version_appended",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_version",
            subject_id=version_id,
            farm_id=None,
            details={"code": code, "version": next_version},
        )
        return await self._tree_with_version(code=code, version=next_version)

    async def discard_version(
        self,
        *,
        code: str,
        version: int,
        actor_user_id: UUID | None,
    ) -> None:
        """Delete one unpublished draft.

        The editor hydrates from the newest version, and `append_version` is a
        no-op when the compiled hash is unchanged. So an author who saved a
        draft they did not want had no way back: re-saving the old body
        returned the existing row, and every later author opened the unwanted
        draft. This is the way back.

        Four things are refused, each because something else is reading the
        row:

        * A published version. It is history. `recommendations.tree_version`
          and `decision_tree_block_verdicts.tree_version` are bare integers
          with no foreign key, so deleting one strands every row naming it.
        * The current version. Covered by the rule above in practice, checked
          on its own because `current_version_id` is what the engine reads.
        * The tree's only version. The editor would have nothing to open, and
          the tree is not deleted by this route — archive it instead.
        * A version some tenant has pinned. `tenant_tree_version_pins.version`
          is an integer with no foreign key either, so the sweep would resolve
          a version that no longer exists.
        """
        tree = await self._own_tree_or_raise(code)
        version_row = await self._repo.get_version_by_number(tree_id=tree["id"], version=version)
        if version_row is None:
            raise _DecisionTreeVersionNotFoundError(code=code, version=version)

        def refuse(reason: str, detail: str) -> _DecisionTreeVersionNotDiscardableError:
            return _DecisionTreeVersionNotDiscardableError(
                code=code, version=version, reason=reason, detail=detail
            )

        if version_row["published_at"] is not None:
            raise refuse(
                "published",
                f"Version {version} of {code!r} is published. A published version is "
                "the record of what the engine ran, so it stays. Publish a different "
                "version to move off it.",
            )
        if tree["current_version_id"] == version_row["id"]:
            raise refuse(
                "current",
                f"Version {version} of {code!r} is the current version. Publish a "
                "different version first.",
            )
        if await self._repo.count_versions(tree_id=tree["id"]) <= 1:
            raise refuse(
                "only_version",
                f"Version {version} is the only version of {code!r}. Discarding it "
                "would leave the editor nothing to open. Archive the tree instead.",
            )
        pins = await self._repo.count_pins_at_version(tree_id=tree["id"], version=version)
        if pins > 0:
            raise refuse(
                "pinned",
                f"Version {version} of {code!r} is pinned by {pins} tenant(s). "
                "They would be left following a version that does not exist.",
            )

        removed = await self._repo.delete_unpublished_version(version_id=version_row["id"])
        if removed == 0:
            # The row was published between the read and the delete. The
            # repository's own `published_at IS NULL` predicate caught it.
            raise refuse(
                "published",
                f"Version {version} of {code!r} was published while this request was "
                "in flight, so it was not discarded.",
            )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_version_discarded",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_version",
            subject_id=version_row["id"],
            farm_id=None,
            details={"code": code, "version": version},
        )

    async def publish_version(
        self,
        *,
        code: str,
        version: int,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        # Writes scope strictly to the caller's own tenant — a tenant
        # cannot publish a version of a platform tree (those are
        # YAML-managed).
        tree = await self._own_tree_or_raise(code)
        version_row = await self._repo.get_version_by_number(tree_id=tree["id"], version=version)
        if version_row is None:
            raise _DecisionTreeVersionNotFoundError(code=code, version=version)
        # Idempotent: republishing a version that's already current is a
        # no-op so the editor's "Publish" button doesn't error if clicked
        # twice.
        if (
            tree["current_version_id"] == version_row["id"]
            and version_row["published_at"] is not None
        ):
            return {
                "code": code,
                "version": version,
                "published_at": version_row["published_at"],
            }
        # Stamp published_at via a direct UPDATE — `insert_version` doesn't
        # have a published-stamp setter for an existing row.
        published_at = clock.now()
        await self._public.execute(
            text(
                "UPDATE public.decision_tree_versions "
                "SET published_at = :pub, published_by = :actor, updated_at = public.app_now() "
                "WHERE id = :vid"
            ),
            {"pub": published_at, "actor": actor_user_id, "vid": version_row["id"]},
        )
        await self._repo.set_current_version(
            tree_id=tree["id"],
            version_id=version_row["id"],
            actor_user_id=actor_user_id,
        )
        # The tree row's display metadata follows whichever version is
        # current. That is what makes "republish an earlier version" a real
        # rollback: without this, publishing v5 after v8 moved the engine
        # back to v5 and left v8's name and description on every screen, so
        # the catalogue described a version nothing was running.
        published = version_row.get("tree_compiled") or {}
        if published:
            crop_path = published.get("crop_path")
            crop_id = await self._repo.resolve_crop_id(
                published.get("crop_code") or (crop_path.split(".")[0] if crop_path else None)
            )
            await self._repo.update_tree_metadata(
                tree_id=tree["id"],
                name_en=published.get("name_en") or tree["name_en"],
                name_ar=published.get("name_ar"),
                description_en=published.get("description_en"),
                description_ar=published.get("description_ar"),
                crop_id=crop_id,
                crop_path=crop_path,
                applicable_regions=published.get("applicable_regions") or [],
                actor_user_id=actor_user_id,
            )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_version_published",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_version",
            subject_id=version_row["id"],
            farm_id=None,
            details={"code": code, "version": version},
        )
        return {"code": code, "version": version, "published_at": published_at}

    # ---- Metadata + lifecycle ----------------------------------------

    async def update_tree(
        self,
        *,
        code: str,
        name_en: str,
        name_ar: str | None,
        description_en: str | None,
        description_ar: str | None,
        crop_paths: list[str],
        country_codes: list[str],
        soil_textures: list[str],
        scope: str,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Full-replace the editable tree-level metadata (name,
        description, multi-axis targeting, scope) from the authoring
        metadata panel. Scoped strictly to the caller's own tenant — a
        tenant cannot edit a platform tree's metadata (those are
        YAML-managed)."""
        tree = await self._own_tree_or_raise(code)
        # Retargeting is the other way a crop-attribute ref goes dead: the
        # YAML never changes, but narrowing the crop set can leave the body
        # branching on an attribute the new crops don't define.
        #
        # Both the published version and the newest draft are checked. The
        # published one is what runs today; the draft is what the author is
        # about to publish, and on a tree created but never published there
        # is no current version at all — checking only that would let the
        # common case (author sets up a tree, then fixes its targeting)
        # through unvalidated.
        for body in await self._versions_to_check(tree):
            await self._assert_crop_attribute_refs_resolve(body, crop_paths=crop_paths)
        # Keep the legacy single-prefix `crop_path` + denormalised
        # `crop_id` populated from the first crop path so the engine's
        # crop resolution and existing reads stay consistent.
        crop_path = crop_paths[0] if crop_paths else None
        crop_id = await self._repo.resolve_crop_id(crop_path.split(".")[0] if crop_path else None)
        await self._repo.update_tree_targeting_metadata(
            tree_id=tree["id"],
            name_en=name_en,
            name_ar=name_ar,
            description_en=description_en,
            description_ar=description_ar,
            crop_id=crop_id,
            crop_path=crop_path,
            crop_paths=crop_paths,
            country_codes=country_codes,
            soil_textures=soil_textures,
            scope=scope,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_metadata_updated",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree["id"],
            farm_id=None,
            details={"code": code},
        )
        detail = await self.get_tree_detail(code=code)
        if detail is None:
            raise _DecisionTreeNotFoundError(code)
        return detail

    async def archive_tree(self, *, code: str, actor_user_id: UUID | None) -> None:
        """Soft-archive one of the caller's own trees. Idempotent-ish:
        the tree must currently be visible (non-archived) — restoring an
        already-archived tree goes through ``restore_tree``."""
        tree = await self._own_tree_or_raise(code)
        await self._repo.set_tree_archived(
            tree_id=tree["id"], archived=True, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_archived",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree["id"],
            farm_id=None,
            details={"code": code},
        )

    async def restore_tree(self, *, code: str, actor_user_id: UUID | None) -> dict[str, Any]:
        """Restore a previously archived tree. Looks the row up
        ``include_deleted`` since an archived tree reads as absent
        everywhere else."""
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=self._tenant_id, include_deleted=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        await self._repo.set_tree_archived(
            tree_id=tree["id"], archived=False, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_restored",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree["id"],
            farm_id=None,
            details={"code": code},
        )
        detail = await self.get_tree_detail(code=code)
        if detail is None:
            raise _DecisionTreeNotFoundError(code)
        return detail

    # ---- Copy, availability, pins -------------------------------------

    def _require_tenant_scope(self) -> UUID:
        """These four operations belong to a tenant and only to a tenant.

        A platform caller has no farms to enable a tree on and no pin to hold,
        so there is nothing here for them to do. The router refuses them first;
        this is the second door.
        """
        if self._tenant_id is None:
            raise _TenantScopeRequiredError()
        return self._tenant_id

    @staticmethod
    def derived_copy_code(code: str, slug: str) -> str:
        """``<original>__<tenant slug>``.

        A tenant copy cannot keep the original's code. ``create_tree`` refuses
        a tenant code that collides with a platform one, and the collision is
        real: ``get_tree_by_code(..., include_platform=True)`` would match two
        rows. The dialog shows this and lets the author change it first.
        """
        cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in slug.lower())
        return f"{code}__{cleaned}"

    async def copy_tree_to_tenant(
        self,
        *,
        code: str,
        new_code: str | None,
        disable_original: bool,
        tenant_session: AsyncSession,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Copy a platform tree into this tenant, optionally turning the
        original off for every farm.

        Two things the copy cannot inherit:

        **Its code.** See ``derived_copy_code``.

        **Its open work.** Recommendations and alerts carry ``tree_code``, and
        the copy's code is different, so open items from the original stay
        open under the original's code. They are real findings somebody may be
        acting on; closing another person's queue is not this operation's
        business. Migration 0079 left the retired mango trees the same way.

        And one thing it does not keep: **later fixes**. A copy never moves
        when the platform republishes the original, and nothing tells the
        tenant it moved. That is the trade the copy makes.

        The copy is published immediately rather than left as a draft. A draft
        plus "disable the original" would leave the tenant running neither.
        """
        import yaml as _yaml

        from app.modules.recommendations.loader import _hash_compiled, compile_tree

        tenant_id = self._require_tenant_scope()
        source = await self._repo.get_tree_by_code(code, scope_tenant_id=None)
        if source is None:
            raise _DecisionTreeNotFoundError(code)
        version_id = source.get("current_version_id")
        if version_id is None:
            raise _DecisionTreeNoPublishedVersionError(code)
        version = await self._repo.get_version(version_id)
        if version is None:
            raise _DecisionTreeNoPublishedVersionError(code)

        slug = await self._repo.get_tenant_slug(tenant_id) or tenant_id.hex[:8]
        target_code = (new_code or self.derived_copy_code(code, slug)).strip()
        collision = await self._repo.get_tree_by_code(
            target_code, scope_tenant_id=tenant_id, include_platform=True
        )
        if collision is not None:
            raise _DecisionTreeCodeAlreadyExistsError(target_code)

        # The body carries the original's `code:`, and compile checks that the
        # body's code matches the row's. Rewrite it through YAML rather than
        # by string replacement, so a tree whose text mentions its own code
        # elsewhere is not silently corrupted.
        spec = _yaml.safe_load(version["tree_yaml"])
        if not isinstance(spec, dict):
            raise _DecisionTreeNotFoundError(code)
        spec["code"] = target_code
        tree_yaml = _yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)
        compiled = compile_tree(spec, source_path=f"<copy:{target_code}>")
        compiled_hash = _hash_compiled(compiled)

        new_tree_id = await self._repo.insert_tree(
            code=target_code,
            tenant_id=tenant_id,
            name_en=compiled["name_en"],
            name_ar=compiled.get("name_ar"),
            description_en=compiled.get("description_en"),
            description_ar=compiled.get("description_ar"),
            crop_id=source.get("crop_id"),
            # From the compiled body, not the source row: `get_tree_by_code`
            # does not carry `crop_path`, so reading it there returns None on
            # every copy and the targeting quietly narrows.
            crop_path=compiled.get("crop_path"),
            crop_paths=list(source.get("crop_paths") or []),
            country_codes=list(source.get("country_codes") or []),
            soil_textures=list(source.get("soil_textures") or []),
            scope=source.get("scope") or "block",
            applicable_regions=list(source.get("applicable_regions") or []),
            actor_user_id=actor_user_id,
        )
        new_version_id = await self._repo.insert_version(
            tree_id=new_tree_id,
            version=1,
            tree_yaml=tree_yaml,
            tree_compiled=compiled,
            compiled_hash=compiled_hash,
            notes=f"Copied from the platform tree {code} at version {version['version']}.",
            published_at=clock.now(),
            published_by=actor_user_id,
        )
        await self._repo.set_current_version(
            tree_id=new_tree_id, version_id=new_version_id, actor_user_id=actor_user_id
        )

        farms_disabled = 0
        if disable_original:
            repo = RecommendationsRepository(
                tenant_session=tenant_session, public_session=self._public
            )
            farms_disabled = await repo.set_tree_excluded_on_every_farm(
                tree_id=source["id"], excluded=True, actor_user_id=actor_user_id
            )

        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_copied",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=new_tree_id,
            farm_id=None,
            details={
                "source_code": code,
                "code": target_code,
                "source_version": version["version"],
                "disabled_original_on_farms": farms_disabled,
            },
        )
        detail = await self.get_tree_detail(code=target_code)
        if detail is None:
            raise _DecisionTreeNotFoundError(target_code)
        detail["disabled_original_on_farms"] = farms_disabled
        return detail

    async def get_tree_availability(
        self, *, code: str, tenant_session: AsyncSession
    ) -> dict[str, Any]:
        """How this tenant runs one tree: on how many farms, at which version,
        and whether that version is held by a pin."""
        tenant_id = self._require_tenant_scope()
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        repo = RecommendationsRepository(tenant_session=tenant_session, public_session=self._public)
        running, total = await repo.count_farms_running_tree(tree_id=tree["id"])
        pinned = await self._repo.get_tree_version_pin(tenant_id=tenant_id, tree_id=tree["id"])
        current: int | None = None
        if tree["current_version_id"] is not None:
            row = await self._repo.get_version(tree["current_version_id"])
            current = None if row is None else row["version"]
        return {
            "code": code,
            "farms_running": running,
            "farms_total": total,
            "enabled_everywhere": total > 0 and running == total,
            "current_version": current,
            "pinned_version": pinned,
        }

    async def set_tree_enabled_everywhere(
        self,
        *,
        code: str,
        enabled: bool,
        tenant_session: AsyncSession,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        """Turn a tree on or off across every farm this tenant has today.

        Every farm that exists **now**. A farm created later inherits nothing
        and runs the tree, so cards can appear from a tree the tenant turned
        off everywhere. The screen says so; there is no state that would make
        it otherwise, because enablement is farm rows and a farm that does not
        exist yet has no row.
        """
        tenant_id = self._require_tenant_scope()
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        repo = RecommendationsRepository(tenant_session=tenant_session, public_session=self._public)
        changed = await repo.set_tree_excluded_on_every_farm(
            tree_id=tree["id"], excluded=not enabled, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_enabled_set",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree["id"],
            farm_id=None,
            details={"code": code, "enabled": enabled, "farms_changed": changed},
        )
        out = await self.get_tree_availability(code=code, tenant_session=tenant_session)
        out["farms_changed"] = changed
        return out

    async def pin_tree_version(
        self, *, code: str, version: int, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        """Hold this tree at one version for this tenant.

        Only a published version can be pinned. Pinning to a draft would take
        the tree out of the sweep entirely — the resolution join requires
        ``published_at IS NOT NULL`` — which is a silent way to turn a tree
        off, and turning a tree off has its own control.
        """
        tenant_id = self._require_tenant_scope()
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        row = await self._repo.get_version_by_number(tree_id=tree["id"], version=version)
        if row is None:
            raise _DecisionTreeVersionNotFoundError(code=code, version=version)
        if row.get("published_at") is None:
            raise _DecisionTreeNoPublishedVersionError(code)
        await self._repo.set_tree_version_pin(
            tenant_id=tenant_id,
            tree_id=tree["id"],
            version=version,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=None,
            event_type="recommendations.decision_tree_version_pinned",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree",
            subject_id=tree["id"],
            farm_id=None,
            details={"code": code, "version": version},
        )
        return {"code": code, "pinned_version": version}

    async def clear_tree_version_pin(
        self, *, code: str, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        """Follow the current version again."""
        tenant_id = self._require_tenant_scope()
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        removed = await self._repo.clear_tree_version_pin(tenant_id=tenant_id, tree_id=tree["id"])
        if removed:
            await self._audit.record(
                tenant_schema=None,
                event_type="recommendations.decision_tree_version_unpinned",
                actor_user_id=actor_user_id,
                actor_kind="user" if actor_user_id else "system",
                subject_kind="decision_tree",
                subject_id=tree["id"],
                farm_id=None,
                details={"code": code},
            )
        return {"code": code, "pinned_version": None}

    # ---- Dry-run ------------------------------------------------------

    async def dry_run(
        self,
        *,
        code: str,
        block_id: UUID,
        version: int | None,
        tree_yaml: str | None,
        tenant_session: AsyncSession,
    ) -> dict[str, Any]:
        """Walk the tree against a real block without writing.

        ``tree_yaml`` (when supplied) wins — the editor can ask "what
        would the unsaved YAML do for this block?" without saving.
        Otherwise the persisted ``version`` is loaded; defaults to the
        current published version if neither is supplied.
        """
        import yaml as _yaml

        from app.modules.recommendations.engine import evaluate_tree
        from app.modules.recommendations.loader import compile_tree

        if tree_yaml is not None:
            spec = _yaml.safe_load(tree_yaml)
            compiled = compile_tree(spec, source_path=f"<dry-run:{code}>")
        else:
            # Dry-run is a read: a tenant can preview a platform tree
            # against their block without writing.
            tree = await self._repo.get_tree_by_code(
                code, scope_tenant_id=self._tenant_id, include_platform=True
            )
            if tree is None:
                raise _DecisionTreeNotFoundError(code)
            target_version = version
            if target_version is None and tree["current_version_id"] is not None:
                # Resolve current version's number from its id.
                current = await self._repo.get_version(tree["current_version_id"])
                if current is None:
                    raise _DecisionTreeNoPublishedVersionError(code)
                target_version = current["version"]
            if target_version is None:
                raise _DecisionTreeNoPublishedVersionError(code)
            row = await self._repo.get_version_by_number(tree_id=tree["id"], version=target_version)
            if row is None:
                raise _DecisionTreeVersionNotFoundError(code=code, version=target_version)
            compiled = row["tree_compiled"]

        # Build the same context the production evaluator would see.
        # Uses tenant_session so we read the right tenant's signals/
        # weather/indices.
        repo = RecommendationsRepository(tenant_session=tenant_session, public_session=self._public)
        from app.modules.grid.snapshot import load_snapshot as load_grid_snapshot
        from app.modules.signals.snapshot import load_snapshot as load_signals_snapshot
        from app.modules.weather.snapshot import (
            load_index_snapshot as load_weather_index_snapshot,
        )
        from app.modules.weather.snapshot import (
            load_risk_snapshot as load_weather_risk_snapshot,
        )
        from app.modules.weather.snapshot import load_snapshot as load_weather_snapshot

        latest_indices = await repo.get_latest_aggregate_per_index(block_id=block_id)
        _merge_index_trends(latest_indices, await repo.get_index_trends(block_id=block_id))
        farm_id = await repo.get_block_farm_id(block_id=block_id)
        (
            dry_run_block_crop_id,
            dry_run_crop_id,
            growth_stage,
            crop_path,
        ) = await repo.get_block_current_crop(block_id=block_id)
        soil_texture, salinity_class = await repo.get_block_soil(block_id=block_id)
        weather = (
            await load_weather_snapshot(tenant_session, farm_id=farm_id)
            if farm_id is not None
            else None
        )
        weather_indices = (
            await load_weather_index_snapshot(tenant_session, farm_id=farm_id)
            if farm_id is not None
            else None
        )
        # Block-keyed, so it loads regardless of farm resolution.
        weather_risks = await load_weather_risk_snapshot(tenant_session, block_id=block_id)
        water_balance = await load_water_balance_snapshot(tenant_session, block_id=block_id)
        signals = (
            await load_signals_snapshot(tenant_session, block_id=block_id, farm_id=farm_id)
            if farm_id is not None
            else None
        )
        # Same grid anomaly snapshot the production evaluator sees, so an
        # author can dry-run a `{source: grid}` predicate against a real
        # block.
        # Keyed by tenant, and a platform caller has no tenant — nor any block
        # to dry-run against, since the routes that reach here all take a
        # tenant session. Skip the snapshot rather than invent a tenant: a
        # `{source: grid}` predicate then fails closed, which is what every
        # other missing source does here.
        grid = (
            await load_grid_snapshot(
                tenant_session, self._public, block_id=block_id, tenant_id=self._tenant_id
            )
            if farm_id is not None and self._tenant_id is not None
            else None
        )
        ctx = ConditionContext.from_block_signals(
            block_id=str(block_id),
            block_attributes={
                "growth_stage": growth_stage,
                "soil_texture": soil_texture,
                "salinity_class": salinity_class,
            },
            latest_index_aggregates=latest_indices,
            weather=weather,
            weather_indices=weather_indices,
            weather_risks=weather_risks,
            water_balance=water_balance,
            signals=signals,
            grid=grid,
            crop_attributes=await load_crop_attribute_snapshot(
                tenant_session, block_crop_id=dry_run_block_crop_id
            ),
        )

        # Targeting is reported, not enforced. The block picker already filters
        # to blocks this tree targets, so an author cannot reach a non-matching
        # block from the UI — but an API caller can, and silently evaluating a
        # tree against a block the sweep would never run it on is exactly the
        # kind of "works in the dry-run, does nothing in production" gap this
        # endpoint exists to close.
        country_code = (
            await repo.get_farm_country_code(farm_id=farm_id) if farm_id is not None else None
        )
        targeting = evaluate_targeting(
            compiled,
            crop_path=crop_path,
            crop_id=dry_run_crop_id,
            country_code=country_code,
            soil_texture=soil_texture,
        )
        targeting_dict = {
            "matched": targeting.matched,
            "axis": targeting.axis,
            "required": list(targeting.required),
            "actual": targeting.actual,
        }

        scope = compiled.get("scope") or "block"
        if scope != "cell":
            result = evaluate_tree(compiled, ctx)
            return {
                "matched": _dry_run_fired(result),
                "scope": scope,
                "targeting": targeting_dict,
                "outcome": _dry_run_outcome(result),
                "path": _serialize_path(result.path),
                "evaluation_snapshot": result.evaluation_snapshot,
                "error": result.error,
                "cells_evaluated": 0,
                "cells_matched": 0,
                "cells": [],
            }

        # Cell-scoped tree: the sweep evaluates it once per grid cell with that
        # cell's imagery means swapped in, so a single block-level walk is not
        # a preview of it — it is a different evaluation that happens to use
        # the same tree. Fan out the same way the sweep does.
        cells, representative = await self._dry_run_cells(
            compiled=compiled,
            repo=repo,
            block_id=block_id,
            base_ctx=ctx,
            latest_indices=latest_indices,
        )
        matched_count = sum(1 for c in cells if c["matched"])
        return {
            "matched": matched_count > 0,
            "scope": scope,
            "targeting": targeting_dict,
            "outcome": _dry_run_outcome(representative) if representative else None,
            "path": _serialize_path(representative.path) if representative else [],
            "evaluation_snapshot": (representative.evaluation_snapshot if representative else {}),
            "error": representative.error if representative else None,
            "cells_evaluated": len(cells),
            "cells_matched": matched_count,
            "cells": cells,
        }

    async def _dry_run_cells(
        self,
        *,
        compiled: Mapping[str, Any],
        repo: RecommendationsRepository,
        block_id: UUID,
        base_ctx: ConditionContext,
        latest_indices: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], EvaluationResult | None]:
        """Walk a ``scope: cell`` tree once per grid cell, as the sweep does.

        Returns every cell's verdict plus the walk that represents the run in
        the canvas highlight: the first cell that fired, or the first cell
        evaluated when none did. Empty for an ungridded block — which is the
        honest answer, since a cell-scoped tree does not fire there either.
        """
        cell_aggs = await repo.get_latest_cell_aggregates(block_id=block_id)
        labels = await repo.get_grid_cell_labels(block_id=block_id)
        cells: list[dict[str, Any]] = []
        representative: EvaluationResult | None = None

        for cid, cell_means in cell_aggs.items():
            # Only the imagery means are per-cell; weather, soil, crop and
            # signals inherit the block. Same locked fidelity rule as the sweep
            # (see _merge_cell_means), and swapping just `indices` on the block
            # context avoids re-loading the inherited snapshots per cell.
            cell_indices = ConditionContext.from_block_signals(
                block_id=base_ctx.block_id,
                latest_index_aggregates=_merge_cell_means(latest_indices, cell_means),
            ).indices
            cell_result = evaluate_tree(compiled, replace(base_ctx, indices=cell_indices))
            fired = _dry_run_fired(cell_result)
            row_idx, col_idx = labels.get(cid, (None, None))
            outcome = cell_result.outcome
            cells.append(
                {
                    "cell_id": str(cid),
                    "cell_row": row_idx,
                    "cell_col": col_idx,
                    "matched": fired,
                    "action_type": outcome.action_type if outcome is not None else None,
                    "severity": outcome.severity if outcome is not None else None,
                    "text_en": outcome.text_en if outcome is not None else None,
                    "error": cell_result.error,
                }
            )
            if representative is None or (fired and not _dry_run_fired(representative)):
                representative = cell_result

        cells.sort(key=lambda c: (c["cell_row"] is None, c["cell_row"], c["cell_col"]))
        return cells, representative

    async def candidate_blocks(
        self, *, code: str, tenant_session: AsyncSession
    ) -> list[dict[str, Any]]:
        """Active blocks this tree would target (dry-run picker, PR-4).

        Filters every active block through the same ``tree_targets_block``
        matcher the sweep uses, so the dropdown offers only blocks whose
        crop / country / soil admit the tree. Returns ``[]`` when nothing
        matches — the UI shows a "no blocks match this tree's targeting"
        message rather than a free-text UUID box.
        """
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=self._tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        repo = RecommendationsRepository(tenant_session=tenant_session, public_session=self._public)
        blocks = await repo.list_blocks_for_targeting()
        out: list[dict[str, Any]] = []
        for b in blocks:
            if not tree_targets_block(
                tree,
                crop_path=b["crop_path"],
                crop_id=b["crop_id"],
                country_code=b["country_code"],
                soil_texture=b["soil_texture"],
            ):
                continue
            farm = b["farm_name"] or ""
            block_label = b["block_name"] or b["block_code"]
            # Arabic falls back per part, not per label: a farm named in
            # Arabic beside a block that is not still reads better than
            # dropping the whole label back to English.
            farm_ar = b["farm_name_ar"] or farm
            block_label_ar = b["block_name_ar"] or block_label
            out.append(
                {
                    "block_id": b["block_id"],
                    "label": f"{farm} / {block_label}" if farm else block_label,
                    "label_ar": (f"{farm_ar} / {block_label_ar}" if farm_ar else block_label_ar),
                }
            )
        return out

    async def candidate_farms(
        self, *, code: str, tenant_session: AsyncSession
    ) -> list[dict[str, Any]]:
        """Farms this tree would fire on, with how many of their blocks it
        targets — drives the "run this tree on a farm" picker.

        Built from the same per-block targeting the dry-run picker uses, then
        rolled up: a farm is offered when at least one of its active blocks
        passes the tree's crop / country / soil filters, and the count is what
        stops an author from running a tree on a 40-block farm where it
        targets one. Farms with no targeted block are omitted entirely rather
        than shown at zero — running there is a guaranteed no-op.
        """
        tree = await self._repo.get_tree_by_code(
            code, scope_tenant_id=self._tenant_id, include_platform=True
        )
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
        repo = RecommendationsRepository(tenant_session=tenant_session, public_session=self._public)
        blocks = await repo.list_blocks_for_targeting()
        farms: dict[UUID, dict[str, Any]] = {}
        for b in blocks:
            farm_id = b["farm_id"]
            entry = farms.setdefault(
                farm_id,
                {
                    "farm_id": farm_id,
                    "name": b["farm_name"] or str(farm_id),
                    "name_ar": b["farm_name_ar"],
                    "blocks_total": 0,
                    "blocks_targeted": 0,
                },
            )
            entry["blocks_total"] += 1
            if tree_targets_block(
                tree,
                crop_path=b["crop_path"],
                crop_id=b["crop_id"],
                country_code=b["country_code"],
                soil_texture=b["soil_texture"],
            ):
                entry["blocks_targeted"] += 1
        return sorted(
            (f for f in farms.values() if f["blocks_targeted"] > 0),
            key=lambda f: f["name"],
        )

    # ---- Internals ----------------------------------------------------

    async def _tree_with_version(self, *, code: str, version: int) -> dict[str, Any]:
        detail = await self.get_tree_detail(code=code)
        if detail is None:
            raise _DecisionTreeNotFoundError(code)
        # Caller wants the version they just touched marked; we leave
        # current_version intact (publish stamps it separately).
        del version
        return detail


# ---- Authoring errors ----------------------------------------------------


class _DecisionTreeAuthoringError(Exception):
    """Base class so the router can map all authoring errors uniformly."""


class _DecisionTreeNotFoundError(_DecisionTreeAuthoringError):
    def __init__(self, code: str) -> None:
        super().__init__(f"No decision tree with code {code!r}")
        self.code = code


class _DecisionTreeVersionNotFoundError(_DecisionTreeAuthoringError):
    def __init__(self, *, code: str, version: int) -> None:
        super().__init__(f"No version {version} for tree {code!r}")
        self.code = code
        self.version = version


class _DecisionTreeCodeAlreadyExistsError(_DecisionTreeAuthoringError):
    def __init__(self, code: str) -> None:
        super().__init__(f"Decision tree {code!r} already exists")
        self.code = code


class _DecisionTreeUnknownCropAttributeError(_DecisionTreeAuthoringError):
    """The tree branches on a crop attribute its target crops don't define.

    Such a ref resolves to None for every block the tree runs on, so the
    comparison fails closed forever — a tree that looks authored and can
    never fire. The condition builder already filters the dropdown by
    targeting; this is the save-time half, for YAML authored by hand or a
    tree whose targeting was narrowed after the fact.
    """

    def __init__(self, *, codes: list[str], crop_paths: list[str]) -> None:
        super().__init__(
            f"crop attribute(s) {', '.join(codes)} are not defined for "
            f"crop path(s) {', '.join(crop_paths)}"
        )
        self.codes = codes
        self.crop_paths = crop_paths


class _DecisionTreeCodeMismatchError(_DecisionTreeAuthoringError):
    def __init__(self, *, expected: str, got: str) -> None:
        super().__init__(f"YAML body has code {got!r} but the URL says {expected!r}")
        self.expected = expected
        self.got = got


class _PlatformTreeNotEditableError(_DecisionTreeAuthoringError):
    """The tree exists, and it is not the caller's to change.

    A platform tree belongs to the platform catalogue, which only a caller
    holding a platform role and no tenant may author. The reason used to be
    that the tree was owned by a YAML file a startup sync rewrote; public
    migration 0085 moved the definitions into the database and the files are
    gone. The refusal to a tenant is unchanged.

    This is its own error because the lookup that refuses it — scoped to the
    caller's own tenant — used to report the tree as missing. "No decision
    tree with code 'x'" about a tree the author has open on screen sends
    somebody hunting for a data problem that does not exist.
    """

    def __init__(self, code: str) -> None:
        super().__init__(
            f"Decision tree {code!r} is a platform tree. Platform trees are managed "
            f"by the platform and cannot be edited here."
        )
        self.code = code


class _TenantScopeRequiredError(_DecisionTreeAuthoringError):
    """A tenant-only authoring operation reached without a tenant.

    Copying, enabling and pinning are things a tenant does to its own farms.
    A platform caller has no farms and no pins, so there is nothing to do.
    """


class _DecisionTreeVersionNotDiscardableError(_DecisionTreeAuthoringError):
    """A version the author asked to discard has to stay.

    Discard exists for one case: an unpublished draft the author no longer
    wants. Everything else named here is either history someone may be
    reading, or the last thing the editor has to open.
    """

    def __init__(self, *, code: str, version: int, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.version = version
        self.reason = reason
        self.detail = detail


class _DecisionTreeNoPublishedVersionError(_DecisionTreeAuthoringError):
    def __init__(self, code: str) -> None:
        super().__init__(f"Decision tree {code!r} has no published version yet")
        self.code = code


class _ParamNameUnknownError(_DecisionTreeAuthoringError):
    """A tenant tried to set an override for a parameter the current
    published tree version doesn't declare. Router maps to 400."""

    def __init__(self, *, code: str, param_name: str) -> None:
        super().__init__(
            f"Tree {code!r} has no declared parameter {param_name!r} in its "
            "current published version"
        )
        self.code = code
        self.param_name = param_name


class _ParamValueCoercionError(_DecisionTreeAuthoringError):
    """An override value couldn't be coerced into the parameter's
    declared type (e.g. ``"banana"`` for a number-typed param).
    Router maps to 400."""

    def __init__(self, *, param_name: str, type_: str, detail: str) -> None:
        super().__init__(f"Override value for {param_name!r} ({type_}) is invalid: {detail}")
        self.param_name = param_name
        self.type_ = type_
        self.detail = detail


def _coerce_override_value(  # noqa: PLR0911, PLR0912
    value: Any, *, declared: dict[str, Any]
) -> Any:
    """Coerce ``value`` (typically from JSON over HTTP) into the
    parameter's declared type. Throws ``_ParamValueCoercionError``
    when the coercion fails or violates min/max/enum constraints.

    Defensive: a permissive form would let a typo'd string slip into
    a numeric parameter and silently break evaluation; we'd rather
    fail loud at the override write than silently at sweep time.
    """
    type_ = declared.get("type")
    if type_ == "number":
        if isinstance(value, bool):
            raise _ParamValueCoercionError(
                param_name=declared.get("name", "?"),
                type_=type_,
                detail="boolean is not a number",
            )
        try:
            num = float(value)  # accepts int/float/numeric string
        except (TypeError, ValueError) as exc:
            raise _ParamValueCoercionError(
                param_name=declared.get("name", "?"), type_=type_, detail=str(exc)
            ) from exc
        return _enforce_min_max(num, declared)
    if type_ == "integer":
        if isinstance(value, bool):
            raise _ParamValueCoercionError(
                param_name=declared.get("name", "?"),
                type_=type_,
                detail="boolean is not an integer",
            )
        try:
            num = int(value)
        except (TypeError, ValueError) as exc:
            raise _ParamValueCoercionError(
                param_name=declared.get("name", "?"), type_=type_, detail=str(exc)
            ) from exc
        return int(_enforce_min_max(num, declared))
    if type_ == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise _ParamValueCoercionError(
            param_name=declared.get("name", "?"),
            type_="boolean",
            detail=f"expected boolean, got {type(value).__name__}",
        )
    if type_ == "string":
        if not isinstance(value, str):
            raise _ParamValueCoercionError(
                param_name=declared.get("name", "?"),
                type_="string",
                detail=f"expected string, got {type(value).__name__}",
            )
        return value
    if type_ == "enum":
        values = declared.get("values") or []
        if value not in values:
            raise _ParamValueCoercionError(
                param_name=declared.get("name", "?"),
                type_="enum",
                detail=f"value {value!r} not in {values}",
            )
        return value
    # Unknown declared type — should never happen because the loader
    # enforces _PARAM_TYPES; pass-through defensively.
    return value


def _enforce_min_max(num: float, declared: dict[str, Any]) -> float:
    lo, hi = declared.get("min"), declared.get("max")
    if lo is not None and num < lo:
        raise _ParamValueCoercionError(
            param_name=declared.get("name", "?"),
            type_=str(declared.get("type")),
            detail=f"value {num} is below min {lo}",
        )
    if hi is not None and num > hi:
        raise _ParamValueCoercionError(
            param_name=declared.get("name", "?"),
            type_=str(declared.get("type")),
            detail=f"value {num} is above max {hi}",
        )
    return num


def get_decision_trees_author_service(
    *, public_session: AsyncSession, tenant_id: UUID | None
) -> DecisionTreesAuthorService:
    return DecisionTreesAuthorService(public_session=public_session, tenant_id=tenant_id)


# ---- Finding catalogue ----------------------------------------------------


class _FindingNotFoundError(_DecisionTreeAuthoringError):
    def __init__(self, code: str) -> None:
        super().__init__(f"No finding with code {code!r}")
        self.code = code


class _FindingCodeAlreadyExistsError(_DecisionTreeAuthoringError):
    def __init__(self, code: str) -> None:
        super().__init__(f"Finding {code!r} already exists")
        self.code = code


class _PlatformFindingNotEditableError(_DecisionTreeAuthoringError):
    """A tenant tried to write the platform catalogue.

    403, not 404: the row is there and the caller can read it. What they
    cannot do is change it, and reporting it as missing sends an author
    looking for a data problem that does not exist.
    """

    def __init__(self, code: str) -> None:
        super().__init__(
            f"Finding {code!r} belongs to the platform catalogue and is read-only here. "
            "The clause is shared by every tenant, which is the reason the catalogue "
            "exists. Add a code of your own instead."
        )
        self.code = code


class FindingsCatalogueService:
    """Author the finding vocabulary, in one of two scopes.

    The scope is the caller's, decided once in the constructor rather than
    per method, because getting it wrong is how a tenant would write a
    shared row. A platform caller (`tenant_schema is None`, platform role)
    acts on `public.decision_tree_findings`. A tenant caller acts on their
    own schema's table and can only read the platform one.

    The resolved read — both catalogues merged, platform winning — is
    `app.modules.recommendations.findings.resolve_findings`, which holds no
    session so the precedence rule can be unit tested directly. This class
    fetches; that function decides.
    """

    def __init__(self, *, repo: FindingsRepository, tenant_schema: str | None) -> None:
        self._repo = repo
        self._tenant_schema = tenant_schema
        self._audit = get_audit_service()

    @property
    def _is_platform_scope(self) -> bool:
        return self._tenant_schema is None

    # ---- Reads --------------------------------------------------------

    async def list_platform(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        """The shared catalogue. Readable in either scope."""
        rows = await self._repo.list_platform(include_inactive=include_inactive)
        return [{**row, "source": PLATFORM_SOURCE, "shadowed": False} for row in rows]

    async def list_tenant(self, *, include_inactive: bool) -> list[dict[str, Any]]:
        """This tenant's own codes, each flagged if the platform shadows it.

        The platform list is fetched too, only to compute `shadowed`. That
        is one extra read of a table with fewer rows than a tree has nodes,
        and without it a tenant author edits a clause, sees no change on
        the card, and has nothing to read that explains it.
        """
        rows = await self._repo.list_tenant(include_inactive=include_inactive)
        platform = await self._repo.list_platform(include_inactive=True)
        shadowed = set(shadowed_codes(platform, rows))
        return [
            {**row, "source": TENANT_SOURCE, "shadowed": row["code"] in shadowed} for row in rows
        ]

    async def resolved(self) -> dict[str, FindingDef]:
        """Both catalogues merged, active rows only, platform winning.

        This is what the compiler validates a tree's `registers` block
        against and what the fold reads to compose a card.
        """
        platform = await self._repo.list_platform(include_inactive=False)
        tenant = await self._repo.list_tenant(include_inactive=False)
        return resolve_findings(platform, tenant)

    # ---- Writes -------------------------------------------------------

    async def create(
        self, *, payload: Mapping[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        code = str(payload["code"])
        existing = (
            await self._repo.get_platform(code=code)
            if self._is_platform_scope
            else await self._repo.get_tenant(code=code)
        )
        if existing is not None:
            raise _FindingCodeAlreadyExistsError(code)

        values = {**payload, "actor": actor_user_id}
        if self._is_platform_scope:
            row = await self._repo.insert_platform(**values)
            source = PLATFORM_SOURCE
            shadowed = False
        else:
            row = await self._repo.insert_tenant(**values)
            source = TENANT_SOURCE
            # A tenant may legally add a code the platform already has: the
            # platform can add one tomorrow and shadow a row that was legal
            # when it was written, so refusing at write time would only move
            # the same situation to a place with no way to report it.
            shadowed = await self._repo.get_platform(code=code) is not None

        await self._record(
            event="finding_created", code=code, actor_user_id=actor_user_id, source=source
        )
        return {**row, "source": source, "shadowed": shadowed}

    async def update(
        self, *, code: str, payload: Mapping[str, Any], actor_user_id: UUID | None
    ) -> dict[str, Any]:
        await self._own_row_or_raise(code)
        values = {**payload, "code": code, "actor": actor_user_id}
        row = (
            await self._repo.update_platform(**values)
            if self._is_platform_scope
            else await self._repo.update_tenant(**values)
        )
        if row is None:
            raise _FindingNotFoundError(code)

        source = PLATFORM_SOURCE if self._is_platform_scope else TENANT_SOURCE
        shadowed = (
            False
            if self._is_platform_scope
            else await self._repo.get_platform(code=code) is not None
        )
        await self._record(
            event="finding_updated", code=code, actor_user_id=actor_user_id, source=source
        )
        return {**row, "source": source, "shadowed": shadowed}

    async def deactivate(self, *, code: str, actor_user_id: UUID | None) -> None:
        """Retire a code. Never a delete — see the repository's note."""
        await self._own_row_or_raise(code)
        touched = (
            await self._repo.deactivate_platform(code=code, actor_user_id=actor_user_id)
            if self._is_platform_scope
            else await self._repo.deactivate_tenant(code=code, actor_user_id=actor_user_id)
        )
        if touched == 0:
            # The row exists — `_own_row_or_raise` just read it — so zero
            # means it was already inactive. Idempotent, nothing to say.
            return
        source = PLATFORM_SOURCE if self._is_platform_scope else TENANT_SOURCE
        await self._record(
            event="finding_deactivated", code=code, actor_user_id=actor_user_id, source=source
        )

    # ---- Internals ----------------------------------------------------

    async def _own_row_or_raise(self, code: str) -> dict[str, Any]:
        """The row this scope may write, or the right refusal.

        A tenant naming a platform code gets 403, not 404, and the two are
        told apart here rather than at the route: only this class knows
        which catalogue the caller is acting on.
        """
        if self._is_platform_scope:
            row = await self._repo.get_platform(code=code)
            if row is None:
                raise _FindingNotFoundError(code)
            return row

        row = await self._repo.get_tenant(code=code)
        if row is not None:
            return row
        if await self._repo.get_platform(code=code) is not None:
            raise _PlatformFindingNotEditableError(code)
        raise _FindingNotFoundError(code)

    async def _record(
        self, *, event: str, code: str, actor_user_id: UUID | None, source: str
    ) -> None:
        await self._audit.record(
            tenant_schema=self._tenant_schema,
            event_type=f"recommendations.{event}",
            actor_user_id=actor_user_id,
            actor_kind="user" if actor_user_id else "system",
            subject_kind="decision_tree_finding",
            # The catalogue is keyed by code, not by a UUID. `subject_kind`
            # carries the meaning and the audit service normalises None to
            # the nil UUID, which is what every non-UUID subject does.
            subject_id=None,
            farm_id=None,
            details={"code": code, "catalogue": source},
        )


def get_findings_catalogue_service(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession | None,
    tenant_schema: str | None,
) -> FindingsCatalogueService:
    return FindingsCatalogueService(
        repo=FindingsRepository(tenant_session=tenant_session, public_session=public_session),
        tenant_schema=tenant_schema,
    )
