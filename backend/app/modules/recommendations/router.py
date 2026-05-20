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

from datetime import date as date_type
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
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
    RecommendationScheduleRequest,
    RecommendationTransitionRequest,
    TreeParameterOverrideResponse,
    TreeParameterOverridesResponse,
    TreeParameterOverrideUpsertRequest,
)

# Importing the private authoring errors to map them at the route layer is
# OK â€” they live in the same module's service.py, not across a module
# boundary.
from app.modules.recommendations.service import (
    DecisionTreesAuthorService,
    RecommendationsServiceImpl,
    _DecisionTreeCodeAlreadyExistsError,
    _DecisionTreeCodeMismatchError,
    _DecisionTreeNoPublishedVersionError,
    _DecisionTreeNotFoundError,
    _DecisionTreeVersionNotFoundError,
    _ParamNameUnknownError,
    _ParamValueCoercionError,
    get_decision_trees_author_service,
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
    return get_recommendations_service(tenant_session=tenant_session, public_session=public_session)


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


# Map decision-tree action_type → board ActivityType. action_type comes
# from the tree YAML (loader.py validates it as a free-form string), so
# unknown values fall through to `observation` — a no-op default that
# never misleads the field operator.
_ACTION_TO_ACTIVITY: dict[str, str] = {
    "irrigate": "irrigation",
    "fertilize": "fertilizing",
    "spray": "spraying",
    "prune": "pruning",
    "scout": "observation",
    "inspect": "observation",
    "harvest_window": "harvesting",
}


@router.post(
    "/recommendations/{recommendation_id}/schedule",
    response_model=dict,  # mirrors plans.ActivityResponse without forcing the import
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a board activity from this recommendation and apply it.",
)
async def schedule_recommendation(
    recommendation_id: UUID,
    payload: RecommendationScheduleRequest,
    context: RequestContext = Depends(get_current_context),
    service: RecommendationsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """One-shot drag-rec-to-cell flow (PR-5).

    Creates a `plan_activities` row with `recommendation_id` set to the
    source rec, then transitions the rec to `applied` in the same
    tenant-session (single DB transaction). Defaults derived from the
    rec — caller can override `block_id`, `activity_type`, `scheduled_date`.
    """
    schema = _ensure_tenant(context)
    rec = await service.get_recommendation(recommendation_id=recommendation_id)
    if rec is None:
        raise RecommendationNotFoundError(recommendation_id)

    farm_id = rec["farm_id"]
    if not has_capability(context, "plan.manage", farm_id=farm_id):
        raise RecommendationNotFoundError(recommendation_id)
    if not has_capability(context, "recommendation.act", farm_id=farm_id):
        raise RecommendationNotFoundError(recommendation_id)
    if rec["state"] not in ("open", "deferred"):
        from app.modules.recommendations.errors import (
            InvalidRecommendationTransitionError,
        )

        raise InvalidRecommendationTransitionError(
            current_state=rec["state"], action="schedule"
        )

    activity_type = payload.activity_type or _ACTION_TO_ACTIVITY.get(
        rec["action_type"], "observation"
    )
    block_id = payload.block_id or rec["block_id"]
    scheduled_date = (
        payload.scheduled_date.date()
        if payload.scheduled_date is not None
        else date_type.today()
    )

    # Local import — plans.service depends on plans.models which references
    # recommendations.models for FK registration. Importing at module top
    # would form a circular registration risk during model finalize.
    from app.modules.plans.service import get_plans_service

    plans = get_plans_service(tenant_session=tenant_session)
    activity = await plans.create_flat_activity(
        farm_id=farm_id,
        block_id=block_id,
        activity_type=activity_type,
        scheduled_date=scheduled_date,
        duration_days=1,
        start_time=None,
        product_name=None,
        dosage=None,
        notes=payload.notes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        recommendation_id=recommendation_id,
    )

    await service.transition_recommendation(
        recommendation_id=recommendation_id,
        action="apply",
        dismissal_reason=None,
        deferred_until=None,
        outcome_notes=(
            f"Scheduled as plan activity {activity['id']} for {scheduled_date.isoformat()}."
        ),
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )

    return activity


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
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    # Scope to platform + own-tenant trees; tenant_id was added by
    # migration 0024 (PR-A).
    rows = (
        (
            await public_session.execute(
                text(
                    """
                SELECT t.id, t.code, t.tenant_id,
                       t.name_en, t.name_ar,
                       t.description_en, t.description_ar,
                       t.crop_id, t.applicable_regions, t.is_active,
                       v.version AS current_version
                FROM public.decision_trees t
                LEFT JOIN public.decision_tree_versions v
                  ON v.id = t.current_version_id
                WHERE t.deleted_at IS NULL
                  AND (t.tenant_id IS NULL OR t.tenant_id = :tid)
                ORDER BY t.tenant_id NULLS FIRST, t.code
                """
                ),
                {"tid": context.tenant_id},
            )
        )
        .mappings()
        .all()
    )
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
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    summary = await service.evaluate_block(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        tenant_id=context.tenant_id,
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
    context: RequestContext = Depends(get_current_context),
) -> DecisionTreesAuthorService:
    # All authoring routes require a tenant-scoped JWT; `_ensure_tenant`
    # in each route handler also raises 403 if tenant_id is missing, so
    # this `assert` is a belt-and-braces — the dependency wiring would
    # have raised 401 long before this point with no tenant_id.
    assert context.tenant_id is not None, "authoring requires a tenant context"
    return get_decision_trees_author_service(
        public_session=public_session, tenant_id=context.tenant_id
    )


def _map_authoring_error(exc: Exception) -> Exception | None:
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
        mapped = _map_authoring_error(_DecisionTreeNotFoundError(code))
        assert mapped is not None
        raise mapped
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
        mapped = _map_authoring_error(_DecisionTreeNotFoundError(code))
        assert mapped is not None
        raise mapped
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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
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
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


# =====================================================================
# Tree parameter overrides (PR-C)
# =====================================================================


def _map_param_override_error(exc: Exception) -> Exception | None:
    """Map PR-C override errors to APIError. Mirrors the authoring
    error mapper pattern so both can be raised from one try/except."""
    from app.core.errors import APIError

    if isinstance(exc, _ParamNameUnknownError):
        return APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Unknown tree parameter",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/recommendations/param-unknown",
            extras={"code": exc.code, "param_name": exc.param_name},
        )
    if isinstance(exc, _ParamValueCoercionError):
        return APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid parameter value",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/recommendations/param-bad-value",
            extras={"param_name": exc.param_name, "type": exc.type_},
        )
    return None


@router.get(
    "/decision-trees/{code}/parameter-overrides",
    response_model=TreeParameterOverridesResponse,
    summary="Read declarations + current overrides for one tree.",
)
async def get_tree_parameter_overrides(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    assert context.tenant_id is not None
    result = await service.list_tree_param_overrides(
        code=code, tenant_id=context.tenant_id
    )
    if not result.get("found"):
        mapped = _map_authoring_error(_DecisionTreeNotFoundError(code))
        assert mapped is not None
        raise mapped
    return {
        "code": result["code"],
        "tree_id": result["tree_id"],
        "declarations": result["declarations"],
        "overrides": result["overrides"],
    }


@router.put(
    "/decision-trees/{code}/parameter-overrides/{param_name}",
    response_model=TreeParameterOverrideResponse,
    summary="Set or replace one parameter override for the calling tenant.",
)
async def upsert_tree_parameter_override(
    code: str,
    param_name: str,
    payload: TreeParameterOverrideUpsertRequest,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    assert context.tenant_id is not None
    try:
        return await service.upsert_tree_param_override(
            code=code,
            tenant_id=context.tenant_id,
            param_name=param_name,
            value=payload.value,
            actor_user_id=context.user_id,
        )
    except Exception as exc:
        mapped = _map_param_override_error(exc) or _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.delete(
    "/decision-trees/{code}/parameter-overrides/{param_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove one override so the tree falls back to its default.",
)
async def delete_tree_parameter_override(
    code: str,
    param_name: str,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> Response:
    _ensure_tenant(context)
    assert context.tenant_id is not None
    try:
        await service.delete_tree_param_override(
            code=code,
            tenant_id=context.tenant_id,
            param_name=param_name,
            actor_user_id=context.user_id,
        )
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)
