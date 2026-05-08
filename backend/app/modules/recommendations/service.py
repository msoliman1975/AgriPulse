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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.recommendations.engine import (
    EvaluationResult,
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
    ) -> dict[str, int]:
        """Run every active tree against ``block_id``; insert new open
        recommendations.
        """
        trees = await self._repo.list_active_trees_with_current_version()
        latest = await self._repo.get_latest_aggregate_per_index(block_id=block_id)
        farm_id = await self._repo.get_block_farm_id(block_id=block_id)
        block_crop_id, crop_id, crop_category = await self._repo.get_block_current_crop(
            block_id=block_id
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
        signals = await load_signals_snapshot(
            self._tenant, block_id=block_id, farm_id=farm_id
        )
        ctx = ConditionContext.from_block_signals(
            block_id=str(block_id),
            crop_category=crop_category,
            latest_index_aggregates=latest,
            weather=weather,
            signals=signals,
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

            result = evaluate_tree(tree["tree_compiled"], ctx)
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

            recommendation_id = uuid7()
            valid_until: datetime | None = None
            if result.outcome.valid_for_hours is not None:
                valid_until = datetime.now(UTC) + timedelta(
                    hours=result.outcome.valid_for_hours
                )

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


def get_recommendations_service(
    *, tenant_session: AsyncSession, public_session: AsyncSession
) -> RecommendationsServiceImpl:
    return RecommendationsServiceImpl(tenant_session=tenant_session, public_session=public_session)


# Type-checker assist: the impl satisfies the Protocol.
def _check(impl: RecommendationsServiceImpl) -> RecommendationsService:
    return impl
