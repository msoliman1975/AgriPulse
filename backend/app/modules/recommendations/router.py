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
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recommendations.errors import (
    DecisionTreeParseError,
    InvalidTreeYamlError,
    RecommendationNotFoundError,
)
from app.modules.recommendations.schemas import (
    BlockVerdictsResponse,
    DecisionTreeCreateRequest,
    DecisionTreeDetailResponse,
    DecisionTreeDryRunRequest,
    DecisionTreeDryRunResponse,
    DecisionTreeResponse,
    DecisionTreeRunRequest,
    DecisionTreeRunResponse,
    DecisionTreeUpdateRequest,
    DecisionTreeVersionCreateRequest,
    DecisionTreeVersionPublishResponse,
    DecisionTreeVersionResponse,
    DryRunCandidateBlock,
    EvalRunResponse,
    EvalTraceDetailResponse,
    EvalTraceResponse,
    EvaluateBlockResponse,
    ExplainBlockResponse,
    FarmTreeSelectionResponse,
    FarmTreeToggleRequest,
    FarmTreeToggleResponse,
    FarmVerdictHistoryResponse,
    FarmVerdictsResponse,
    RecommendationResponse,
    RecommendationScheduleRequest,
    RecommendationTransitionRequest,
    StatusDefinitionResponse,
    TreeParameterOverrideResponse,
    TreeParameterOverridesResponse,
    TreeParameterOverrideUpsertRequest,
    TreeRunCandidateFarm,
    VerdictReasoningResponse,
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
    _DecisionTreeUnknownCropAttributeError,
    _DecisionTreeVersionNotFoundError,
    _ParamNameUnknownError,
    _ParamValueCoercionError,
    _PlatformTreeNotEditableError,
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
    # SMK-RBAC-GAP-02: gate on the farm in scope so a farm-scoped-only user can
    # read their farm's recommendations (the page always passes ?farm_id=).
    # Tenant/platform callers still pass via their tenant role (farm_id ignored).
    context: RequestContext = Depends(
        requires_capability("recommendation.read", farm_id_param="farm_id")
    ),
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
    context: RequestContext = Depends(get_current_context),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """Gated on the farm the recommendation is for, not on the tenant.

    The route is keyed on a recommendation id, so there is no farm in the path
    for `requires_capability` to read, and without one the resolver stops
    before the farm tier — which denied every farm-scoped caller. The row
    carries `farm_id`, so it is read first and the check runs against that.

    A caller without the grant gets the same 404 as a caller naming an id that
    does not exist. Answering 403 would confirm the recommendation is real.
    """
    _ensure_tenant(context)
    rec = await service.get_recommendation(recommendation_id=recommendation_id)
    if rec is None:
        raise RecommendationNotFoundError(recommendation_id)
    if not has_capability(context, "recommendation.read", farm_id=rec["farm_id"]):
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

    # Read the row first: `recommendation.act` is a farm-tier capability, and
    # checking it without a farm never reaches the farm tier — so an
    # Agronomist could not act on a recommendation for their own farm.
    rec = await service.get_recommendation(recommendation_id=recommendation_id)
    if rec is None:
        raise RecommendationNotFoundError(recommendation_id)
    if not has_capability(context, "recommendation.act", farm_id=rec["farm_id"]):
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

        raise InvalidRecommendationTransitionError(current_state=rec["state"], action="schedule")

    activity_type = payload.activity_type or _ACTION_TO_ACTIVITY.get(
        rec["action_type"], "observation"
    )
    block_id = payload.block_id or rec["block_id"]
    scheduled_date = (
        payload.scheduled_date.date() if payload.scheduled_date is not None else date_type.today()
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
    summary="Decision-tree catalog (active by default).",
)
async def list_decision_trees(
    status_filter: Literal["active", "archived", "all"] = Query(
        "active",
        alias="status",
        description="active = non-archived (default); archived = soft-deleted only; all = both.",
    ),
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    # The archived filter drives the soft-delete clause; the engine +
    # every other read still filter deleted_at IS NULL unconditionally,
    # so archived trees only ever surface here behind an explicit status.
    if status_filter == "active":
        archived_clause = "t.deleted_at IS NULL"
    elif status_filter == "archived":
        archived_clause = "t.deleted_at IS NOT NULL"
    else:
        archived_clause = "TRUE"
    # Scope to platform + own-tenant trees; tenant_id was added by
    # migration 0024 (PR-A).
    rows = (
        (
            await public_session.execute(
                text(
                    f"""
                SELECT t.id, t.code, t.tenant_id,
                       t.name_en, t.name_ar,
                       t.description_en, t.description_ar,
                       t.crop_id, t.crop_paths, t.country_codes,
                       t.soil_textures, t.scope, t.applicable_regions, t.is_active,
                       (t.deleted_at IS NOT NULL) AS archived,
                       v.version AS current_version
                FROM public.decision_trees t
                LEFT JOIN public.decision_tree_versions v
                  ON v.id = t.current_version_id
                WHERE {archived_clause}
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
    # A single-block run, traced like the sweep. This is the debug path, so it
    # is the one an author reaches for first — leaving it untraced would mean
    # the button labelled "run this now" produced less evidence than the
    # unattended nightly job.
    run_id = await service.repo.open_eval_run(kind="on_demand", actor_user_id=context.user_id)
    summary = await service.evaluate_block(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        tenant_id=context.tenant_id,
        run_id=run_id,
    )
    await service.repo.close_eval_run(
        run_id=run_id,
        blocks_evaluated=1,
        trees_evaluated=summary["trees_evaluated"],
        trees_skipped=summary["trees_skipped_crop"],
        recommendations_opened=summary["recommendations_opened"],
        alerts_opened=0,
        traces_written=summary.get("traces_written", 0),
    )
    return {
        "block_id": str(block_id),
        "run_id": str(run_id),
        "trees_evaluated": summary["trees_evaluated"],
        "trees_skipped_crop": summary["trees_skipped_crop"],
        "recommendations_opened": summary["recommendations_opened"],
        "traces_written": summary.get("traces_written", 0),
        "verdicts_written": summary.get("verdicts_written", 0),
    }


@router.get(
    "/blocks/{block_id}/decision-trees:explain",
    response_model=ExplainBlockResponse,
    summary="Why each decision tree did or didn't fire on this block (read-only).",
)
async def explain_block(
    block_id: UUID,
    farm_id: UUID = Query(
        ...,
        description=(
            "The block's parent farm. Required because it is what the request "
            "is authorized against — a farm-scoped user has no tenant-wide "
            "role to fall back on. Verified against the block."
        ),
    ),
    context: RequestContext = Depends(
        requires_capability("recommendation.read", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """Read model behind the Farm Console's Conditions tab.

    Unlike ``:evaluate`` (POST) this opens nothing — it re-walks the trees
    against the block's current signals purely to report the reasoning,
    including for trees that came out clear and so leave no row behind.

    Gated on ``recommendation.read``, NOT ``decision_tree.read`` like its
    neighbours here. This endpoint explains recommendations, so everyone who
    can see one should be able to see why it fired — and that is the whole
    audience for it: Agronomist, FarmManager, Scout and Viewer all hold
    ``recommendation.read`` but none of them hold ``decision_tree.read``.
    Widening ``decision_tree.read`` instead is not an option: it also gates
    ``:evaluate`` and ``:dry-run``, both of which write.

    Authorization is scoped by the ``farm_id`` query parameter, mirroring
    ``GET /recommendations``. Without it ``requires_capability`` has no farm
    to test scopes against, so a user whose only grant is a farm scope is
    denied no matter which capability the route names.
    """
    _ensure_tenant(context)
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    return await service.explain_block(
        block_id=block_id, tenant_id=context.tenant_id, farm_id=farm_id
    )


# =====================================================================
# Evaluation lineage (tenant 0062)
# =====================================================================
#
# Registered under their own `/decision-tree-*` paths rather than under
# `/decision-trees/…`, where a literal segment would have to be declared
# ahead of the existing `/decision-trees/{code}` routes to avoid being
# swallowed by them — a route-ordering dependency that breaks silently the
# next time someone reorders this file.


@router.get(
    "/decision-tree-runs",
    response_model=list[EvalRunResponse],
    summary="Recorded decision-tree evaluation runs, newest first.",
)
async def list_eval_runs(
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.repo.list_eval_runs(limit=limit)


@router.get(
    "/decision-tree-traces",
    response_model=list[EvalTraceResponse],
    summary="Per-tree verdicts from recorded runs (why a tree did or didn't fire).",
)
async def list_eval_traces(
    run_id: UUID | None = Query(default=None),
    block_id: UUID | None = Query(default=None),
    farm_id: UUID | None = Query(default=None),
    tree_code: str | None = Query(default=None),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=1000),
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    """The list view. Excludes the node walk and the resolved values — those
    are megabytes per page and only ever read one row at a time."""
    _ensure_tenant(context)
    return await service.repo.list_eval_traces(
        run_id=run_id,
        block_id=block_id,
        farm_id=farm_id,
        tree_code=tree_code,
        status_filter=tuple(status_filter or ()),
        limit=limit,
    )


@router.get(
    "/decision-tree-traces/{trace_id}",
    response_model=EvalTraceDetailResponse,
    summary="One evaluation trace with its full node walk and resolved values.",
)
async def get_eval_trace(
    trace_id: UUID,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    from app.core.errors import APIError

    _ensure_tenant(context)
    row = await service.repo.get_eval_trace(trace_id=trace_id)
    if row is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Evaluation trace not found",
            detail=f"No evaluation trace {trace_id} in this tenant.",
            type_="https://agripulse.cloud/problems/eval-trace-not-found",
        )
    return row


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


def _map_authoring_error(exc: Exception) -> Exception | None:  # noqa: PLR0911 - dispatch
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
    if isinstance(exc, _DecisionTreeUnknownCropAttributeError):
        return APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Unknown crop attribute",
            detail=(
                f"{exc} — the tree would branch on a value none of its blocks "
                "can carry, so the comparison would never match."
            ),
            type_="https://agripulse.cloud/problems/recommendations/unknown-crop-attribute",
            extras={"codes": exc.codes, "crop_paths": exc.crop_paths},
        )
    if isinstance(exc, _DecisionTreeCodeMismatchError):
        return APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Decision tree code mismatch",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/recommendations/decision-tree-code-mismatch",
            extras={"expected": exc.expected, "got": exc.got},
        )
    if isinstance(exc, _PlatformTreeNotEditableError):
        # 403, not 404. The tree is there and the caller can read it; what
        # they cannot do is change it. Reporting it as missing sent an author
        # looking for a data problem that did not exist.
        return APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Platform tree is read-only",
            detail=str(exc),
            type_="https://agripulse.cloud/problems/recommendations/platform-tree-read-only",
            extras={"code": exc.code},
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
            crop_paths=payload.crop_paths,
            country_codes=payload.country_codes,
            soil_textures=payload.soil_textures,
            scope=payload.scope,
            actor_user_id=context.user_id,
        )
    except DecisionTreeParseError as exc:
        # Caller-supplied YAML: a 422, not the loader's server-fixture 500.
        raise InvalidTreeYamlError.from_parse_error(exc) from exc
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
    except DecisionTreeParseError as exc:
        # Caller-supplied YAML: a 422, not the loader's server-fixture 500.
        raise InvalidTreeYamlError.from_parse_error(exc) from exc
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


@router.patch(
    "/decision-trees/{code}",
    response_model=DecisionTreeDetailResponse,
    summary="Update a tree's editable metadata (name, description, targeting, scope).",
)
async def update_decision_tree(
    code: str,
    payload: DecisionTreeUpdateRequest,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    try:
        return await service.update_tree(
            code=code,
            name_en=payload.name_en,
            name_ar=payload.name_ar,
            description_en=payload.description_en,
            description_ar=payload.description_ar,
            crop_paths=payload.crop_paths,
            country_codes=payload.country_codes,
            soil_textures=payload.soil_textures,
            scope=payload.scope,
            actor_user_id=context.user_id,
        )
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.delete(
    "/decision-trees/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive (soft-delete) a decision tree.",
)
async def archive_decision_tree(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> Response:
    _ensure_tenant(context)
    try:
        await service.archive_tree(code=code, actor_user_id=context.user_id)
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/decision-trees/{code}:restore",
    response_model=DecisionTreeDetailResponse,
    summary="Restore a previously archived decision tree.",
)
async def restore_decision_tree(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    try:
        return await service.restore_tree(code=code, actor_user_id=context.user_id)
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.get(
    "/decision-trees/{code}/candidate-blocks",
    response_model=list[DryRunCandidateBlock],
    summary="Active blocks this tree would target (dry-run picker).",
)
async def list_dry_run_candidate_blocks(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.read")),
    service: DecisionTreesAuthorService = Depends(_author_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    try:
        return await service.candidate_blocks(code=code, tenant_session=tenant_session)
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
    except DecisionTreeParseError as exc:
        # Caller-supplied YAML: a 422, not the loader's server-fixture 500.
        raise InvalidTreeYamlError.from_parse_error(exc) from exc
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


# ---------- On-demand tree run (authoring) --------------------------------
#
# The dry-run's counterpart. `:dry-run` answers "what would this decide
# here?" and writes nothing; `:run` decides it and puts the result in the
# Action Center. Both live in the authoring surface because they are the two
# halves of testing a tree — preview, then commit.


@router.get(
    "/decision-trees/{code}/candidate-farms",
    response_model=list[TreeRunCandidateFarm],
    summary="Farms this tree targets, with targeted-block counts (run picker).",
)
async def list_tree_run_candidate_farms(
    code: str,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: DecisionTreesAuthorService = Depends(_author_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    try:
        return await service.candidate_farms(code=code, tenant_session=tenant_session)
    except Exception as exc:
        mapped = _map_authoring_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise


@router.post(
    "/decision-trees/{code}:run",
    response_model=DecisionTreeRunResponse,
    summary="Run this tree's published version across one farm, for real.",
)
async def run_decision_tree_on_farm(
    code: str,
    payload: DecisionTreeRunRequest,
    context: RequestContext = Depends(requires_capability("decision_tree.manage")),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """Evaluate one tree over every active block of ``farm_id`` and open the
    recommendations it produces.

    Gated on ``decision_tree.manage``, not the ``decision_tree.read`` its
    neighbours use: this writes rows that reach the whole farm team through
    the Action Center and the notification pipeline. Reading a tree and
    dispatching work from it are different privileges.

    Not farm-scoped via ``farm_id_param``. ``decision_tree.manage`` is a
    tenant-scoped capability held only by TenantOwner / TenantAdmin, so
    there is no farm-scope grant for it to resolve against — adding the
    parameter would imply an authorization path that does not exist.

    Synchronous by design. A farm is a bounded number of blocks and the
    author needs the verdict while they still have the tree in front of
    them; handing back a task id would put the one result that matters
    behind a poll.
    """
    schema = _ensure_tenant(context)
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    return await service.run_tree_on_farm(
        tree_code=code,
        farm_id=payload.farm_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        tenant_id=context.tenant_id,
    )


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
    result = await service.list_tree_param_overrides(code=code, tenant_id=context.tenant_id)
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


# ---------- Farm-level tree selection (tenant 0089) -------------------------


@router.get(
    "/farms/{farm_id}/decision-trees",
    response_model=FarmTreeSelectionResponse,
    summary="List the decision trees this farm runs, and the ones it turned off.",
)
async def list_farm_decision_trees(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    rows = await service.list_farm_tree_selection(farm_id=farm_id, tenant_id=context.tenant_id)
    return {"farm_id": farm_id, "trees": list(rows)}


@router.put(
    "/farms/{farm_id}/decision-trees/{tree_id}",
    response_model=FarmTreeToggleResponse,
    summary="Turn one decision tree on or off for this farm.",
)
async def set_farm_decision_tree(
    farm_id: UUID,
    tree_id: UUID,
    payload: FarmTreeToggleRequest,
    context: RequestContext = Depends(
        requires_capability("farm.manage_config", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    assert context.tenant_id is not None  # _ensure_tenant guarantees
    return await service.set_farm_tree_enabled(
        farm_id=farm_id,
        tree_id=tree_id,
        tenant_id=context.tenant_id,
        enabled=payload.enabled,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# =====================================================================
# Verdicts (tenant 0091)
# =====================================================================
#
# What each tree says about a block, including the trees that found nothing
# wrong. Registered under `/verdict-*` and `/farms/{farm_id}/verdicts` rather
# than under `/decision-trees/…`, where a literal segment would have to be
# declared ahead of `/decision-trees/{code}` to avoid being swallowed by it —
# a route-ordering dependency that breaks silently on the next reorder.


@router.get(
    "/verdict-statuses",
    response_model=list[StatusDefinitionResponse],
    summary="The five platform status codes, with colour and both labels.",
)
async def list_verdict_statuses(
    context: RequestContext = Depends(requires_capability("recommendation.read", any_farm=True)),
    service: RecommendationsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    """The legend. Served rather than shipped in the frontend bundle.

    ``any_farm`` because the list belongs to no farm: it is the same five
    rows for everyone. Naming neither that nor a farm parameter would deny
    every farm-scoped caller — a Scout holds their capabilities on a farm and
    has no tenant-wide role to fall back on — and the denial is a silent 403
    on a request that looks correct.
    """
    _ensure_tenant(context)
    return service.status_catalog()


@router.get(
    "/blocks/{block_id}/verdicts",
    response_model=BlockVerdictsResponse,
    summary="What each tree says about one block.",
)
async def get_block_verdicts(
    block_id: UUID,
    farm_id: UUID = Query(
        ...,
        description=(
            "The block's parent farm. Required because it is what the request "
            "is authorized against — a farm-scoped user has no tenant-wide "
            "role to fall back on."
        ),
    ),
    at: datetime | None = Query(
        default=None,
        description=(
            "Replay: what the trees said at this instant. Omitted, the "
            "current answers are returned."
        ),
    ),
    context: RequestContext = Depends(
        requires_capability("recommendation.read", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """One block's verdicts, plus the worst of them, which is what it reads as.

    A tree missing from the list did not run on this block — excluded by
    targeting, turned off for the farm, archived, or the sweep never reached
    it. That absence is the point of the table: before it existed, "checked
    and fine" and "never ran" were the same blank.

    Gated on ``recommendation.read`` rather than ``decision_tree.read``, for
    the same reason as ``:explain``: this is what a block's readers see, and
    Agronomist, FarmManager, Scout and Viewer all hold the first and none
    hold the second.
    """
    _ensure_tenant(context)
    return await service.block_verdicts(block_id=block_id, at=at)


@router.get(
    "/farms/{farm_id}/verdict-history",
    response_model=FarmVerdictHistoryResponse,
    summary="Every verdict that stood at any point in a date window.",
)
async def get_farm_verdict_history(
    farm_id: UUID,
    from_at: datetime = Query(
        ...,
        alias="from",
        description="Start of the window, inclusive.",
    ),
    to_at: datetime = Query(
        ...,
        alias="to",
        description="End of the window, exclusive.",
    ),
    tree_code: str | None = Query(
        default=None,
        description=(
            "One tree. The map shows one tree at a time, and filtering here "
            "rather than in the client is what keeps a year inside one "
            "response."
        ),
    ),
    context: RequestContext = Depends(
        requires_capability("recommendation.read", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """The replay, in one request.

    `/farms/{farm_id}/verdicts?at=` answers one instant. A day-by-day replay
    over a year would call it 365 times for a farm whose answers change a
    handful of times. This returns the intervals themselves, once.

    `from` and `to` are query aliases because `from` is a Python keyword.
    """
    from app.core.errors import APIError

    _ensure_tenant(context)
    if to_at <= from_at:
        raise APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Empty window",
            detail="`to` must be after `from`.",
            type_="https://agripulse.cloud/problems/verdict-history-empty-window",
        )
    return await service.farm_verdict_history(
        farm_id=farm_id, from_at=from_at, to_at=to_at, tree_code=tree_code
    )


@router.get(
    "/blocks/{block_id}/verdicts/{verdict_id}/reasoning",
    response_model=VerdictReasoningResponse,
    summary="The node walk behind one verdict.",
)
async def get_verdict_reasoning(
    block_id: UUID,
    verdict_id: UUID,
    farm_id: UUID = Query(
        ...,
        description=(
            "The block's parent farm. Required because it is what the request "
            "is authorized against — a farm-scoped user has no tenant-wide "
            "role to fall back on."
        ),
    ),
    context: RequestContext = Depends(
        requires_capability("recommendation.read", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """Why this verdict, with the values the tree read.

    `/decision-tree-traces/{id}` answers the same question for a tree author
    and is gated on `decision_tree.read`. FarmManager, Agronomist,
    FieldOperator, Scout and Viewer hold `recommendation.read` and not that
    one, so pointing the map at the author's endpoint would 403 every reader
    it was built for. This is the same walk, gated the way the verdict reads
    are.

    `reasoning_available` is false when retention has pruned the run behind
    the verdict. The verdict still stands and its status is still correct;
    only the walk is gone. That is a different sentence from "no such
    verdict", which is a 404, so the two are not collapsed.
    """
    _ensure_tenant(context)
    from app.core.errors import APIError

    row = await service.verdict_reasoning(block_id=block_id, verdict_id=verdict_id)
    if row is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Verdict not found",
            detail=f"No verdict {verdict_id} on block {block_id} in this tenant.",
            type_="https://agripulse.cloud/problems/verdict-not-found",
        )
    return row


@router.get(
    "/farms/{farm_id}/verdicts",
    response_model=FarmVerdictsResponse,
    summary="Every block of one farm, with what each tree says about it.",
)
async def get_farm_verdicts(
    farm_id: UUID,
    at: datetime | None = Query(
        default=None,
        description=(
            "Replay: what the trees said at this instant. Omitted, the "
            "current answers are returned."
        ),
    ),
    context: RequestContext = Depends(
        requires_capability("recommendation.read", farm_id_param="farm_id")
    ),
    service: RecommendationsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    """The whole farm in one statement.

    The map reads this. A block with no verdicts is absent rather than
    present and empty: this read cannot tell "no tree ran here" from "no such
    block", and an empty entry would invite a map to paint a confident grey
    over the second case.
    """
    _ensure_tenant(context)
    return await service.farm_verdicts(farm_id=farm_id, at=at)
