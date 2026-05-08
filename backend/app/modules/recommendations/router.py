"""FastAPI routes for the recommendations module.

Mounted under /api/v1 by the app factory. Endpoints:

  GET    /recommendations                                — list (filterable)
  GET    /recommendations/{recommendation_id}            — detail with tree path
  PATCH  /recommendations/{recommendation_id}            — apply / dismiss / defer
  GET    /decision-trees                                 — catalog list
  POST   /blocks/{block_id}/recommendations:evaluate     — admin/debug eval

RBAC:
  * Reads use ``recommendation.read`` and ``decision_tree.read``.
  * Apply / dismiss / defer require ``recommendation.act``.
  * On-demand evaluation requires ``decision_tree.read`` (anyone with
    that capability can also kick a sweep — the data already exists,
    we're just synthesising it earlier).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.errors import RecommendationNotFoundError
from app.modules.recommendations.schemas import (
    DecisionTreeResponse,
    EvaluateBlockResponse,
    RecommendationResponse,
    RecommendationTransitionRequest,
)
from app.modules.recommendations.service import (
    RecommendationsServiceImpl,
    get_recommendations_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> RecommendationsServiceImpl:
    return get_recommendations_service(
        tenant_session=tenant_session, public_session=public_session
    )


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://missionagre.io/problems/tenant-required",
        )
    return schema


# ---------- Recommendations ------------------------------------------------


@router.get(
    "/recommendations",
    response_model=list[RecommendationResponse],
    summary="List recommendations in the current tenant.",
)
async def list_recommendations(
    farm_id: UUID | None = Query(default=None),
    block_id: UUID | None = Query(default=None),
    state_filter: list[str] | None = Query(default=None, alias="state"),
    action_type: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability("recommendation.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = await service.list_recommendations(
        farm_id=farm_id,
        block_id=block_id,
        state_filter=tuple(state_filter or ()),
        action_type_filter=tuple(action_type or ()),
        limit=limit,
    )
    return list(rows)


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    summary="Read one recommendation, including its full tree path.",
)
async def get_recommendation(
    recommendation_id: UUID,
    context: RequestContext = Depends(requires_capability("recommendation.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    rec = await service.get_recommendation(recommendation_id=recommendation_id)
    if rec is None:
        raise RecommendationNotFoundError(recommendation_id)
    return rec


@router.patch(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    summary="Apply / dismiss / defer a recommendation.",
)
async def transition_recommendation(
    recommendation_id: UUID,
    payload: RecommendationTransitionRequest,
    context: RequestContext = Depends(get_current_context),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)

    chosen = sum(
        1
        for v in (
            payload.apply,
            payload.dismiss,
            payload.defer_until is not None,
        )
        if v
    )
    if chosen != 1:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid transition payload",
            detail="Exactly one of `apply`, `dismiss`, `defer_until` must be set.",
            type_="https://missionagre.io/problems/recommendation-invalid-transition",
        )
    if payload.apply:
        action = "apply"
    elif payload.dismiss:
        action = "dismiss"
    else:
        action = "defer"

    if not has_capability(context, "recommendation.act"):
        # Mirrors alerts/router: a caller with read but not act sees a
        # 404 for the transition path, since they got the id from the
        # list and we don't want to leak existence beyond the read scope.
        raise RecommendationNotFoundError(recommendation_id)

    return await service.transition_recommendation(
        recommendation_id=recommendation_id,
        action=action,
        dismissal_reason=payload.dismissal_reason,
        deferred_until=payload.defer_until,
        outcome_notes=payload.outcome_notes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---------- Decision-tree catalog -----------------------------------------


@router.get(
    "/decision-trees",
    response_model=list[DecisionTreeResponse],
    summary="Active decision-tree catalog.",
)
async def list_decision_trees(
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = (
        await public_session.execute(
            text(
                """
                SELECT t.id, t.code, t.name_en, t.name_ar,
                       t.description_en, t.description_ar,
                       t.crop_id, t.applicable_regions, t.is_active,
                       v.version AS current_version
                FROM public.decision_trees t
                LEFT JOIN public.decision_tree_versions v
                  ON v.id = t.current_version_id
                WHERE t.deleted_at IS NULL
                ORDER BY t.code
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------- On-demand evaluation -----------------------------------------


@router.post(
    "/blocks/{block_id}/recommendations:evaluate",
    response_model=EvaluateBlockResponse,
    summary="Run the recommendations engine for one block (admin / debug).",
)
async def evaluate_block(
    block_id: UUID,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    summary = await service.evaluate_block(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
    return {
        "block_id": str(block_id),
        "trees_evaluated": summary["trees_evaluated"],
        "trees_skipped_crop": summary["trees_skipped_crop"],
        "recommendations_opened": summary["recommendations_opened"],
    }
