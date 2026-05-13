"""FastAPI routes for the recommendations module.

Mounted under /api/v1 by the app factory. Endpoints:

  GET    /recommendations                                â€” list (filterable)
  GET    /recommendations/{recommendation_id}            â€” detail with tree path
  PATCH  /recommendations/{recommendation_id}            â€” apply / dismiss / defer
  GET    /decision-trees                                 â€” catalog list
  POST   /blocks/{block_id}/recommendations:evaluate     â€” admin/debug eval

RBAC:
  * Reads use ``recommendation.read`` and ``decision_tree.read``.
  * Apply / dismiss / defer require ``recommendation.act``.
  * On-demand evaluation requires ``decision_tree.read`` (anyone with
    that capability can also kick a sweep â€” the data already exists,
    we're just synthesising it earlier).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.errors import (
    DecisionTreeParseError,
    RecommendationNotFoundError,
)
from app.modules.recommendations.schemas import (
    DecisionTreeCreateRequest,
    DecisionTreeDetailResponse,
    DecisionTreeDryRunRequest,
    DecisionTreeDryRunResponse,
    DecisionTreeResponse,
    DecisionTreeVersionCreateRequest,
    DecisionTreeVersionPublishResponse,
    DecisionTreeVersionResponse,
    EvaluateBlockResponse,
    RecommendationResponse,
    RecommendationTransitionRequest,
)
from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    RecommendationsServiceImpl,
    get_decision_trees_author_service,
    get_recommendations_service,
)
# Importing the private authoring errors to map them at the route layer is
# OK â€” they live in the same module's service.py, not across a module
# boundary.
from app.modules.recommendations.service import (  # noqa: E402
    _DecisionTreeCodeAlreadyExistsError,
    _DecisionTreeCodeMismatchError,
    _DecisionTreeNoPublishedVersionError,
    _DecisionTreeNotFoundError,
    _DecisionTreeVersionNotFoundError,
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
            type_="https://agripulse.cloud/problems/tenant-required",
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
            type_="https://agripulse.cloud/problems/recommendation-invalid-transition",
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


# =====================================================================
# Decision-tree authoring (PlatformAdmin)
# =====================================================================


def _author_service(
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> DecisionTreesAuthorService:
    return get_decision_trees_author_service(public_session=public_session)


def _map_authoring_error(exc: Exception) -> "RuntimeError | None":
    """Map authoring-service errors to APIError, return one to raise.

    Centralised so each endpoint stays focused on the happy path."""
    from app.core.errors import APIError

    if isinstance(exc, _DecisionTreeNotFoundError):
        return APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Decision tree not found",
            detail=f"No decision tree with code {exc.code!r}.",
            type_="https://agripulse.cloud/problems/recommendations/decision-tree-not-found",
            extras={"code": exc.code},
        )
    if isinstance(exc, _DecisionTreeVersionNotFoundError):
        return APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Decision tree version not found",
            detail=f"Tree {exc.code!r} has no version {exc.version}.",
            type_="https://agripulse.cloud/problems/recommendations/decision-tree-version-not-found",
            extras={"code": exc.code, "version": exc.version},
        )
    if isinstance(exc, _DecisionTreeCodeAlreadyExistsError):
        return APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="Decision tree code already exists",
            detail=f"A decision tree with code {exc.code!r} already exists.",
            type_="https://agripulse.cloud/problems/recommendations/decision-tree-code-conflict",
            extras={"code": exc.code},
        )
    if isinstance(exc, _DecisionTreeCodeMismatchError):
        return APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Decision tree code mismatch",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/recommendations/decision-tree-code-mismatch",
            extras={"expected": exc.expected, "got": exc.got},
        )
    if isinstance(exc, _DecisionTreeNoPublishedVersionError):
        return APIError(
            status_code=status.HTTP_409_CONFLICT,
            title="No published version",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/recommendations/decision-tree-no-published-version",
            extras={"code": exc.code},
        )
    return None


@router.get(
    "/decision-trees/{code}",
    response_model=DecisionTreeDetailResponse,
    summary="Read one decision tree with full version history.",
)
async def get_decision_tree(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    detail = await service.get_tree_detail(code=code)
    if detail is None:
        raise _map_authoring_error(_DecisionTreeNotFoundError(code))  # type: ignore[arg-type]
    return detail


@router.get(
    "/decision-trees/{code}/versions",
    response_model=list[DecisionTreeVersionResponse],
    summary="List the version history for one decision tree.",
)
async def list_decision_tree_versions(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    detail = await service.get_tree_detail(code=code)
    if detail is None:
        raise _map_authoring_error(_DecisionTreeNotFoundError(code))  # type: ignore[arg-type]
    return detail["versions"]


@router.post(
    "/decision-trees",
    response_model=DecisionTreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new decision tree (first version is a draft).",
)
async def create_decision_tree(
    payload: DecisionTreeCreateRequest,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    try:
        return await service.create_tree(
            code=payload.code,
            crop_code=payload.crop_code,
            tree_yaml=payload.tree_yaml,
            actor_user_id=context.user_id,
        )
    except DecisionTreeParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.post(
    "/decision-trees/{code}/versions",
    response_model=DecisionTreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append a new draft version to an existing decision tree.",
)
async def append_decision_tree_version(
    code: str,
    payload: DecisionTreeVersionCreateRequest,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    try:
        return await service.append_version(
            code=code,
            tree_yaml=payload.tree_yaml,
            notes=payload.notes,
            actor_user_id=context.user_id,
        )
    except DecisionTreeParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.post(
    "/decision-trees/{code}/versions/{version}:publish",
    response_model=DecisionTreeVersionPublishResponse,
    summary="Mark a draft version as the current published version.",
)
async def publish_decision_tree_version(
    code: str,
    version: int,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    try:
        return await service.publish_version(
            code=code,
            version=version,
            actor_user_id=context.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.post(
    "/decision-trees/{code}:dry-run",
    response_model=DecisionTreeDryRunResponse,
    summary="Evaluate a tree (saved or unsaved) against a real block without writing.",
)
async def dry_run_decision_tree(
    code: str,
    payload: DecisionTreeDryRunRequest,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: DecisionTreesAuthorService = Depends(_author_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    _ensure_tenant(context)
    try:
        return await service.dry_run(
            code=code,
            block_id=payload.block_id,
            version=payload.version,
            tree_yaml=payload.tree_yaml,
            tenant_session=tenant_session,
        )
    except DecisionTreeParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
