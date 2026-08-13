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

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
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
    TreePathStep,
    evaluate_tree,
)
from app.modules.recommendations.errors import (
    BlockNotInFarmError,
    InvalidRecommendationTransitionError,
    RecommendationNotFoundError,
)
from app.modules.recommendations.events import (
    RecommendationAppliedV1,
    RecommendationDeferredV1,
    RecommendationDismissedV1,
    RecommendationOpenedV1,
)
from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.signals.snapshot import load_snapshot as load_signals_snapshot
from app.modules.weather.snapshot import load_index_snapshot as load_weather_index_snapshot
from app.modules.weather.snapshot import load_risk_snapshot as load_weather_risk_snapshot
from app.modules.weather.snapshot import load_snapshot as load_weather_snapshot
from app.modules.weather.snapshot import load_water_balance_snapshot
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
    ) -> None:
        full = status in _FULL_PAYLOAD_STATUSES
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
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)

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
    ) -> dict[str, int]:
        """Run every active tree visible to this tenant against
        ``block_id``; insert new open recommendations.

        ``tenant_id`` scopes the catalog lookup to platform trees +
        this tenant's own authored trees. The Beat task resolves this
        once per tenant before walking blocks (PR-A).

        ``run_id`` opts this evaluation into trace capture: every tree's
        verdict — including the ones that came out clear or were excluded by
        targeting — is recorded against that run. Omitted, nothing is written
        beyond the recommendations themselves, which keeps the many tests that
        drive this method directly from needing a run row.
        """
        setup = await self._prepare_block_evaluation(block_id=block_id, tenant_id=tenant_id)
        if setup is None:
            return {
                "trees_evaluated": 0,
                "trees_skipped_crop": 0,
                "recommendations_opened": 0,
                "traces_written": 0,
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
            if (
                await self._evaluate_and_record(
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
                )
                is not None
            ):
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
        )

    async def _prepare_block_evaluation(
        self,
        *,
        block_id: UUID,
        tenant_id: UUID,
    ) -> _BlockEvaluation | None:
        """Load the trees, signals and targeting split for ``block_id``.

        Returns ``None`` when the block has no parent farm (nothing can be
        evaluated). Performs no writes, so both the sweep and the read-only
        explain endpoint can call it.
        """
        trees = await self._repo.list_active_trees_with_current_version(
            visible_to_tenant_id=tenant_id
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

        # PR-C: bulk-load tenant parameter overrides for every tree the
        # sweep will walk. One query, grouped by tree_id; engine falls
        # back to declared defaults for trees with no overrides.
        param_overrides_per_tree = await self._repo.list_all_param_overrides_visible_to_tenant(
            tree_ids=tuple(t["tree_id"] for t in trees)
        )

        # Split matched trees by execution scope (PR-C3). Block-scoped trees
        # evaluate once against the block context; cell-scoped trees fan out
        # over the block's grid cells (cell imagery, inherit everything else).
        block_trees: list[dict[str, Any]] = []
        cell_trees: list[dict[str, Any]] = []
        skipped_trees: list[tuple[dict[str, Any], TargetingVerdict]] = []
        for tree in trees:
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
    ) -> dict[str, int]:
        """Run the cell-scoped trees and emit their digest notifications."""
        farm_id = setup.farm_id
        block_crop_id = setup.block_crop_id
        crop_path = setup.crop_path
        cell_trees = setup.cell_trees
        param_overrides_per_tree = setup.param_overrides_per_tree

        # Cell-scoped path (PR-C3): one evaluation per grid cell, with the
        # cell's own imagery means swapped into an otherwise block-level
        # context. Empty when the block has no grid, so cell trees no-op there.
        # Per (cell-scoped tree) tally of opened recommendations, so we can emit
        # one digest notification per (tree, block) instead of one per cell.
        cell_rec_digest: dict[UUID, dict[str, Any]] = {}
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
                    )
                    if opened is None:
                        continue
                    recommendations_opened += 1
                    if opened["kind"] == "recommendation":
                        # First opened rec per tree is the digest's representative
                        # (notification links to it); track count + worst severity.
                        agg = cell_rec_digest.setdefault(
                            tree["tree_id"],
                            {"tree": tree, "count": 0, "first": opened},
                        )
                        agg["count"] += 1
                        if _SEVERITY_RANK.get(opened["severity"], 0) > _SEVERITY_RANK.get(
                            agg["first"]["severity"], 0
                        ):
                            agg["first"] = {**agg["first"], "severity": opened["severity"]}

        # One aggregated notification per cell-scoped tree that opened ≥1 rec on
        # this block: publish a single synthetic *block-level* (cell_id=None)
        # RecommendationOpenedV1 with digest text. The notifications module
        # suppresses the per-cell events and fans this out through the normal
        # rec pipeline — one "N zones flagged" notification instead of N.
        for agg in cell_rec_digest.values():
            tree = agg["tree"]
            first = agg["first"]
            count = agg["count"]
            self._bus.publish(
                RecommendationOpenedV1(
                    recommendation_id=first["recommendation_id"],
                    block_id=block_id,
                    cell_id=None,
                    farm_id=farm_id,
                    tree_id=tree["tree_id"],
                    tree_code=tree["tree_code"],
                    tree_version=tree["version"],
                    action_type=first["action_type"],
                    severity=first["severity"],
                    confidence=Decimal("1.0"),
                    created_at=datetime.now(UTC),
                    tenant_schema=tenant_schema,
                    text_en=(
                        f"{count} zones flagged in this block — "
                        "review per-zone recommendations on the map."
                    ),
                    text_ar=(
                        f"تم وضع علامة على {count} منطقة في هذا الحقل — "
                        "راجع التوصيات لكل منطقة على الخريطة."
                    ),
                    zone_count=count,
                )
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
        }

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
            if fired and outcome is not None:
                entry.update(
                    kind=outcome.kind,
                    action_type=outcome.action_type,
                    severity=outcome.severity,
                    confidence=float(outcome.confidence),
                    text_en=outcome.text_en,
                    text_ar=outcome.text_ar,
                )
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
            "evaluated_at": datetime.now(UTC),
            "crop_path": setup.crop_path,
            "trees": trees,
        }

    async def _evaluate_and_record(
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
            )

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
            # Either a malformed leaf or an explicit "no action" leaf — record
            # nothing; the daily evaluator re-walks tomorrow as signals change.
            _trace("clear")
            return None

        leaf_outcome = {
            "kind": result.outcome.kind,
            "action_type": result.outcome.action_type,
            "severity": result.outcome.severity,
            "confidence": str(result.outcome.confidence),
            # The last step of the walk is the leaf that produced this outcome.
            "leaf_node_id": result.path[-1].node_id if result.path else None,
        }

        # PR-E: dispatch on leaf kind. "alert" leaves write to tenant.alerts;
        # "recommendation" leaves take the path below.
        if result.outcome.kind == "alert":
            opened = await self._open_alert_from_tree(
                block_id=block_id,
                cell_id=cell_id,
                farm_id=farm_id,
                tree=tree,
                result=result,
                actor_user_id=actor_user_id,
                tenant_schema=tenant_schema,
            )
            if opened is None:
                # The tree still fired — an open alert for this (block, rule)
                # already existed and deduped it away. Recording this as
                # anything but `fired` would misattribute the silence to the
                # conditions rather than to the dedup.
                _trace("fired", outcome={**leaf_outcome, "deduped": True})
                return None
            _trace("fired", outcome=leaf_outcome, alert_id=opened)
            return {
                "kind": "alert",
                # Was the literal string "alert" — a placeholder from when the
                # alert row had nowhere to keep the leaf's verb. It does now.
                "action_type": result.outcome.action_type,
                "severity": result.outcome.severity,
            }

        recommendation_id = uuid7()
        valid_until: datetime | None = None
        if result.outcome.valid_for_hours is not None:
            valid_until = datetime.now(UTC) + timedelta(hours=result.outcome.valid_for_hours)

        # Snapshot the block's crop path (+ cell id when cell-scoped) alongside
        # the evaluated signals so the recommendation stays self-describing.
        snapshot: dict[str, Any] = {**result.evaluation_snapshot, "crop_path": crop_path}
        if cell_id is not None:
            snapshot["cell_id"] = str(cell_id)

        inserted = await self._repo.insert_recommendation(
            recommendation_id=recommendation_id,
            block_id=block_id,
            cell_id=cell_id,
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
        )
        if not inserted:
            # An open recommendation for (block[/cell], tree) already exists.
            # Same reasoning as the alert dedup above: the tree fired, the
            # idempotency index absorbed it.
            _trace("fired", outcome={**leaf_outcome, "deduped": True})
            return None
        _trace("fired", outcome=leaf_outcome, recommendation_id=recommendation_id)

        await self._repo.insert_history(
            recommendation_id=recommendation_id,
            block_id=block_id,
            cell_id=cell_id,
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
        self._bus.publish(
            RecommendationOpenedV1(
                recommendation_id=recommendation_id,
                block_id=block_id,
                cell_id=cell_id,
                farm_id=farm_id,
                tree_id=tree["tree_id"],
                tree_code=tree["tree_code"],
                tree_version=tree["version"],
                action_type=result.outcome.action_type,
                severity=result.outcome.severity,
                confidence=result.outcome.confidence,
                created_at=datetime.now(UTC),
                tenant_schema=tenant_schema,
                text_en=result.outcome.text_en,
                text_ar=result.outcome.text_ar,
                parameters=result.outcome.parameters,
                evaluation_snapshot=result.evaluation_snapshot,
            )
        )
        return {
            "kind": "recommendation",
            "recommendation_id": recommendation_id,
            "action_type": result.outcome.action_type,
            "severity": result.outcome.severity,
            "text_en": result.outcome.text_en,
            "text_ar": result.outcome.text_ar,
        }

    async def _open_alert_from_tree(
        self,
        *,
        block_id: UUID,
        cell_id: UUID | None = None,
        farm_id: UUID,
        tree: dict[str, Any],
        result: Any,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> UUID | None:
        """Open an alert produced by a tree-leaf with ``kind: alert``.

        PR-E: trees can now emit alerts as well as recommendations.
        We synthesise a ``rule_code`` of the form
        ``f"tree:{tree_code}:{leaf_node_id}"`` so the existing
        ``alerts`` partial-UNIQUE on ``(block_id, rule_code)`` keeps
        dedup semantics intact across re-evaluations. PR-F retires
        rule-sourced alerts entirely, at which point all rows in
        ``tenant.alerts`` carry tree-shaped rule_codes.

        Returns the new alert's id iff a row was newly inserted, else None
        (the partial UNIQUE blocked a duplicate while a prior alert is still
        open/acknowledged/snoozed). The id is what lets an evaluation trace
        link to the alert it produced.
        """
        from app.modules.alerts.events import AlertOpenedV1
        from app.modules.alerts.repository import AlertsRepository

        outcome = result.outcome
        leaf_node_id = outcome.leaf_node_id or "leaf"
        rule_code = f"tree:{tree['tree_code']}:{leaf_node_id}"
        # Cell-scoped alerts embed the cell id so the existing
        # (block_id, rule_code) dedup keeps each cell's alert distinct (PR-C3).
        if cell_id is not None:
            rule_code = f"{rule_code}:cell:{cell_id}"
        alert_id = uuid7()
        alert_repo = AlertsRepository(tenant_session=self._tenant, public_session=self._public)
        inserted = await alert_repo.insert_alert(
            alert_id=alert_id,
            block_id=block_id,
            cell_id=cell_id,
            rule_code=rule_code,
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
        )
        if not inserted:
            return None

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
                "cell_id": str(cell_id) if cell_id else None,
                "rule_code": rule_code,
                "severity": outcome.severity,
                "action_type": outcome.action_type,
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "leaf_node_id": leaf_node_id,
            },
        )
        self._bus.publish(
            AlertOpenedV1(
                alert_id=alert_id,
                block_id=block_id,
                cell_id=cell_id,
                rule_code=rule_code,
                severity=outcome.severity,
                created_at=datetime.now(UTC),
                tenant_schema=tenant_schema,
                farm_id=farm_id,
                diagnosis_en=outcome.text_en,
                diagnosis_ar=outcome.text_ar,
                prescription_en=None,
                prescription_ar=None,
                signal_snapshot=result.evaluation_snapshot,
            )
        )
        return alert_id

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

    def __init__(self, *, public_session: AsyncSession, tenant_id: UUID) -> None:
        """``tenant_id`` is the caller's tenant (from ``RequestContext``).

        It scopes every read to platform PLUS this tenant, and stamps
        every authoring write with this tenant's UUID, so tenant-A's
        trees are never visible to or writable by tenant-B. The YAML
        seed loader is the only writer that produces platform rows
        (``tenant_id IS NULL``) — there is no API path to that.
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
        tree = await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id)
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
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
        # Sync the human-friendly metadata on the tree row even before
        # publish so the catalog list reflects what the author last saved.
        crop_path = compiled.get("crop_path")
        crop_id = await self._repo.resolve_crop_id(
            compiled.get("crop_code") or (crop_path.split(".")[0] if crop_path else None)
        )
        await self._repo.update_tree_metadata(
            tree_id=tree["id"],
            name_en=compiled["name_en"],
            name_ar=compiled.get("name_ar"),
            description_en=compiled.get("description_en"),
            description_ar=compiled.get("description_ar"),
            crop_id=crop_id,
            crop_path=crop_path,
            applicable_regions=compiled.get("applicable_regions") or [],
            actor_user_id=actor_user_id,
        )
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

    async def publish_version(
        self,
        *,
        code: str,
        version: int,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        # Writes scope strictly to the caller's own tenant — a tenant
        # cannot author a new version of a platform tree (those are
        # YAML-managed). Platform-tree customization in PR-C goes
        # through a separate override path, not version-append.
        tree = await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id)
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
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
        published_at = datetime.now(UTC)
        await self._public.execute(
            text(
                "UPDATE public.decision_tree_versions "
                "SET published_at = :pub, published_by = :actor, updated_at = now() "
                "WHERE id = :vid"
            ),
            {"pub": published_at, "actor": actor_user_id, "vid": version_row["id"]},
        )
        await self._repo.set_current_version(
            tree_id=tree["id"],
            version_id=version_row["id"],
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
        tree = await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id)
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
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
        tree = await self._repo.get_tree_by_code(code, scope_tenant_id=self._tenant_id)
        if tree is None:
            raise _DecisionTreeNotFoundError(code)
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
        grid = (
            await load_grid_snapshot(
                tenant_session, self._public, block_id=block_id, tenant_id=self._tenant_id
            )
            if farm_id is not None
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
            out.append(
                {
                    "block_id": b["block_id"],
                    "label": f"{farm} / {block_label}" if farm else block_label,
                }
            )
        return out

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
    *, public_session: AsyncSession, tenant_id: UUID
) -> DecisionTreesAuthorService:
    return DecisionTreesAuthorService(public_session=public_session, tenant_id=tenant_id)
