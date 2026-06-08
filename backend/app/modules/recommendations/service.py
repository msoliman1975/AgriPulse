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

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.grid.snapshot import load_snapshot as load_grid_snapshot
from app.modules.recommendations.engine import (
    TreePathStep,
    evaluate_tree,
)
from app.modules.recommendations.errors import (
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
from app.modules.weather.snapshot import load_snapshot as load_weather_snapshot
from app.shared.conditions import ConditionContext
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus


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

    # ---- Engine driver ------------------------------------------------

    async def evaluate_block(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        tenant_id: UUID,
    ) -> dict[str, int]:
        """Run every active tree visible to this tenant against
        ``block_id``; insert new open recommendations.

        ``tenant_id`` scopes the catalog lookup to platform trees +
        this tenant's own authored trees. The Beat task resolves this
        once per tenant before walking blocks (PR-A).
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
        block_crop_id, crop_id, crop_category, growth_stage = (
            await self._repo.get_block_current_crop(block_id=block_id)
        )

        if farm_id is None:
            self._log.info("recommendations_skip_no_farm", block_id=str(block_id))
            return {
                "trees_evaluated": 0,
                "trees_skipped_crop": 0,
                "recommendations_opened": 0,
            }

        # Pull weather + signals once per evaluation pass. Both loaders
        # return empty data when the block has no provider/observation
        # rows yet, so predicates fail closed instead of spuriously firing.
        weather = await load_weather_snapshot(self._tenant, farm_id=farm_id)
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
        ctx = ConditionContext.from_block_signals(
            block_id=str(block_id),
            crop_category=crop_category,
            block_attributes={"growth_stage": growth_stage},
            latest_index_aggregates=latest,
            weather=weather,
            signals=signals,
            grid=grid,
        )

        # PR-C: bulk-load tenant parameter overrides for every tree the
        # sweep will walk. One query, grouped by tree_id; engine falls
        # back to declared defaults for trees with no overrides.
        param_overrides_per_tree = await self._repo.list_all_param_overrides_visible_to_tenant(
            tree_ids=tuple(t["tree_id"] for t in trees)
        )

        trees_evaluated = 0
        trees_skipped_crop = 0
        recommendations_opened = 0
        for tree in trees:
            # Per-crop trees only apply when the block's current crop
            # matches. Crop-agnostic trees (crop_id is NULL) always apply.
            if tree["crop_id"] is not None and tree["crop_id"] != crop_id:
                trees_skipped_crop += 1
                continue
            trees_evaluated += 1

            overrides = param_overrides_per_tree.get(tree["tree_id"], {})
            result = evaluate_tree(tree["tree_compiled"], ctx, param_overrides=overrides)
            if result.error is not None:
                self._log.warning(
                    "decision_tree_walk_error",
                    tree_code=tree["tree_code"],
                    block_id=str(block_id),
                    error=result.error,
                )
                continue
            if result.outcome is None or result.outcome.action_type == "no_action":
                # Either malformed leaf or an explicit "no action" leaf —
                # we record nothing, the daily evaluator will re-walk
                # tomorrow when signals change.
                continue

            # PR-E: dispatch on leaf kind. "alert" leaves write to
            # tenant.alerts via the alerts repo (rule_code synthesised
            # from tree + leaf id so the existing partial-UNIQUE
            # dedup keeps working); "recommendation" leaves take the
            # existing path below.
            if result.outcome.kind == "alert":
                opened = await self._open_alert_from_tree(
                    block_id=block_id,
                    farm_id=farm_id,
                    tree=tree,
                    result=result,
                    actor_user_id=actor_user_id,
                    tenant_schema=tenant_schema,
                )
                if opened:
                    recommendations_opened += 1  # counter is generic; rename in PR-F
                continue

            recommendation_id = uuid7()
            valid_until: datetime | None = None
            if result.outcome.valid_for_hours is not None:
                valid_until = datetime.now(UTC) + timedelta(hours=result.outcome.valid_for_hours)

            inserted = await self._repo.insert_recommendation(
                recommendation_id=recommendation_id,
                block_id=block_id,
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
                evaluation_snapshot=result.evaluation_snapshot,
                actor_user_id=actor_user_id,
            )
            if not inserted:
                # An open recommendation for (block, tree) already exists.
                # Re-evaluation is intentionally idempotent.
                continue
            recommendations_opened += 1

            await self._repo.insert_history(
                recommendation_id=recommendation_id,
                block_id=block_id,
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
            "trees_evaluated": trees_evaluated,
            "trees_skipped_crop": trees_skipped_crop,
            "recommendations_opened": recommendations_opened,
        }

    async def _open_alert_from_tree(
        self,
        *,
        block_id: UUID,
        farm_id: UUID,
        tree: dict[str, Any],
        result: Any,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> bool:
        """Open an alert produced by a tree-leaf with ``kind: alert``.

        PR-E: trees can now emit alerts as well as recommendations.
        We synthesise a ``rule_code`` of the form
        ``f"tree:{tree_code}:{leaf_node_id}"`` so the existing
        ``alerts`` partial-UNIQUE on ``(block_id, rule_code)`` keeps
        dedup semantics intact across re-evaluations. PR-F retires
        rule-sourced alerts entirely, at which point all rows in
        ``tenant.alerts`` carry tree-shaped rule_codes.

        Returns True iff a row was newly inserted (the partial UNIQUE
        blocked a duplicate while a prior alert is still
        open/acknowledged/snoozed).
        """
        from app.modules.alerts.events import AlertOpenedV1
        from app.modules.alerts.repository import AlertsRepository

        outcome = result.outcome
        leaf_node_id = outcome.leaf_node_id or "leaf"
        rule_code = f"tree:{tree['tree_code']}:{leaf_node_id}"
        alert_id = uuid7()
        alert_repo = AlertsRepository(tenant_session=self._tenant, public_session=self._public)
        inserted = await alert_repo.insert_alert(
            alert_id=alert_id,
            block_id=block_id,
            rule_code=rule_code,
            severity=outcome.severity,
            diagnosis_en=outcome.text_en,
            diagnosis_ar=outcome.text_ar,
            prescription_en=None,
            prescription_ar=None,
            prescription_activity_id=None,
            signal_snapshot=result.evaluation_snapshot,
            actor_user_id=actor_user_id,
        )
        if not inserted:
            return False

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
                "rule_code": rule_code,
                "severity": outcome.severity,
                "tree_code": tree["tree_code"],
                "tree_version": tree["version"],
                "leaf_node_id": leaf_node_id,
            },
        )
        self._bus.publish(
            AlertOpenedV1(
                alert_id=alert_id,
                block_id=block_id,
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
        return True

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
            "applicable_regions": tree["applicable_regions"],
            "is_active": tree["is_active"],
            "current_version": current_version_number,
            "versions": [dict(v) for v in versions],
        }

    # ---- Writes -------------------------------------------------------

    async def create_tree(
        self,
        *,
        code: str,
        crop_code: str | None,
        tree_yaml: str,
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
        compiled = compile_tree(spec, source_path=f"<api:{code}>")
        # The compiled body's `code` field must match the URL — protect
        # against a typo where the YAML says one thing and the URL another.
        if compiled.get("code") != code:
            raise _DecisionTreeCodeMismatchError(expected=code, got=str(compiled.get("code")))
        compiled_hash = _hash_compiled(compiled)
        crop_id = await self._repo.resolve_crop_id(crop_code)

        tree_id = await self._repo.insert_tree(
            code=code,
            tenant_id=self._tenant_id,
            name_en=compiled["name_en"],
            name_ar=compiled.get("name_ar"),
            description_en=compiled.get("description_en"),
            description_ar=compiled.get("description_ar"),
            crop_id=crop_id,
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
        crop_id = await self._repo.resolve_crop_id(compiled.get("crop_code"))
        await self._repo.update_tree_metadata(
            tree_id=tree["id"],
            name_en=compiled["name_en"],
            name_ar=compiled.get("name_ar"),
            description_en=compiled.get("description_en"),
            description_ar=compiled.get("description_ar"),
            crop_id=crop_id,
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
        from app.modules.weather.snapshot import load_snapshot as load_weather_snapshot

        latest_indices = await repo.get_latest_aggregate_per_index(block_id=block_id)
        _merge_index_trends(latest_indices, await repo.get_index_trends(block_id=block_id))
        farm_id = await repo.get_block_farm_id(block_id=block_id)
        _, _, crop_category, growth_stage = await repo.get_block_current_crop(
            block_id=block_id
        )
        weather = (
            await load_weather_snapshot(tenant_session, farm_id=farm_id)
            if farm_id is not None
            else None
        )
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
            crop_category=crop_category,
            block_attributes={"growth_stage": growth_stage},
            latest_index_aggregates=latest_indices,
            weather=weather,
            signals=signals,
            grid=grid,
        )
        result = evaluate_tree(compiled, ctx)
        outcome_dict: dict[str, Any] | None = None
        if result.outcome is not None:
            outcome_dict = {
                "action_type": result.outcome.action_type,
                "severity": result.outcome.severity,
                "confidence": str(result.outcome.confidence),
                "parameters": result.outcome.parameters,
                "text_en": result.outcome.text_en,
                "text_ar": result.outcome.text_ar,
                "valid_for_hours": result.outcome.valid_for_hours,
                "actions": result.outcome.actions,
            }
        return {
            "matched": result.outcome is not None and result.outcome.action_type != "no_action",
            "outcome": outcome_dict,
            "path": _serialize_path(result.path),
            "evaluation_snapshot": result.evaluation_snapshot,
            "error": result.error,
        }

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


def _coerce_override_value(value: Any, *, declared: dict[str, Any]) -> Any:  # noqa: PLR0911, PLR0912 - dispatch over declared types
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
