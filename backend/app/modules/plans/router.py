"""FastAPI routes for the plans module.

Mounted under /api/v1 by the app factory. Endpoints:

  POST   /farms/{farm_id}/plans
  GET    /farms/{farm_id}/plans
  GET    /farms/{farm_id}/plans/calendar?from=&to=
  GET    /plans/{plan_id}
  PATCH  /plans/{plan_id}
  DELETE /plans/{plan_id}                                  — soft-archive
  POST   /plans/{plan_id}/activities
  GET    /plans/{plan_id}/activities
  PATCH  /activities/{activity_id}                         — metadata + state actions

RBAC:
  * Reads use ``plan.read``.
  * Plan create/update/archive + activity create/update use ``plan.manage``.
  * State transitions on activities (``state=complete|skip``) use the
    finer-grained ``plan_activity.complete`` so FieldOperators can mark
    activities done without being granted full plan management.
"""

from datetime import date as date_type
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plans.errors import PlanNotFoundError
from app.modules.plans.schemas import (
    ActivityCreateRequest,
    ActivityResponse,
    ActivityUpdateRequest,
    CalendarResponse,
    PlanCreateRequest,
    PlanResponse,
    PlanUpdateRequest,
)
from app.modules.plans.service import PlansServiceImpl, get_plans_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["plans"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> PlansServiceImpl:
    return get_plans_service(tenant_session=tenant_session)


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


# ---------- Plans ----------------------------------------------------------


@router.post(
    "/farms/{farm_id}/plans",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a vegetation plan for a farm.",
)
async def create_plan(
    farm_id: UUID,
    payload: PlanCreateRequest,
    context: RequestContext = Depends(requires_capability("plan.manage", farm_id_param="farm_id")),
    service: PlansServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.create_plan(
        farm_id=farm_id,
        season_label=payload.season_label,
        season_year=payload.season_year,
        name=payload.name,
        notes=payload.notes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.get(
    "/farms/{farm_id}/plans",
    response_model=list[PlanResponse],
    summary="List vegetation plans for a farm.",
)
async def list_plans(
    farm_id: UUID,
    season_year: int | None = Query(default=None),
    include_archived: bool = Query(default=False),
    context: RequestContext = Depends(requires_capability("plan.read", farm_id_param="farm_id")),
    service: PlansServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = await service.list_plans(
        farm_id=farm_id,
        season_year=season_year,
        include_archived=include_archived,
    )
    return list(rows)


@router.get(
    "/farms/{farm_id}/plans/calendar",
    response_model=CalendarResponse,
    summary="Activities scheduled in a date window across all plans for a farm.",
)
async def list_calendar(
    farm_id: UUID,
    from_date: date_type = Query(alias="from"),
    to_date: date_type = Query(alias="to"),
    context: RequestContext = Depends(requires_capability("plan.read", farm_id_param="farm_id")),
    service: PlansServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    rows = await service.list_calendar(farm_id=farm_id, from_date=from_date, to_date=to_date)
    return {"farm_id": str(farm_id), "activities": list(rows)}


@router.get(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    summary="Get a vegetation plan.",
)
async def get_plan(
    plan_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: PlansServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    plan = await service.get_plan(plan_id=plan_id)
    # Per-farm gate on plan.read — plan rows carry farm_id, so we
    # resolve and check after the fetch (matches imagery's pattern).
    if not has_capability(context, "plan.read", farm_id=plan["farm_id"]):
        raise PlanNotFoundError(plan_id)
    return plan


@router.patch(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    summary="Update plan metadata or status.",
)
async def update_plan(
    plan_id: UUID,
    payload: PlanUpdateRequest,
    context: RequestContext = Depends(get_current_context),
    service: PlansServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    plan = await service.get_plan(plan_id=plan_id)
    if not has_capability(context, "plan.manage", farm_id=plan["farm_id"]):
        raise PlanNotFoundError(plan_id)
    changes = payload.model_dump(exclude_unset=True)
    return await service.update_plan(
        plan_id=plan_id,
        changes=changes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive (soft-delete) a vegetation plan.",
    response_model=None,
)
async def archive_plan(
    plan_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: PlansServiceImpl = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    plan = await service.get_plan(plan_id=plan_id)
    if not has_capability(context, "plan.manage", farm_id=plan["farm_id"]):
        raise PlanNotFoundError(plan_id)
    await service.archive_plan(
        plan_id=plan_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---------- Activities ----------------------------------------------------


@router.post(
    "/plans/{plan_id}/activities",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Schedule a new activity on a plan.",
)
async def create_activity(
    plan_id: UUID,
    payload: ActivityCreateRequest,
    context: RequestContext = Depends(get_current_context),
    service: PlansServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    plan = await service.get_plan(plan_id=plan_id)
    if not has_capability(context, "plan.manage", farm_id=plan["farm_id"]):
        raise PlanNotFoundError(plan_id)
    return await service.create_activity(
        plan_id=plan_id,
        block_id=payload.block_id,
        activity_type=payload.activity_type,
        scheduled_date=payload.scheduled_date,
        duration_days=payload.duration_days,
        start_time=payload.start_time,
        product_name=payload.product_name,
        dosage=payload.dosage,
        notes=payload.notes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.get(
    "/plans/{plan_id}/activities",
    response_model=list[ActivityResponse],
    summary="List activities for a plan.",
)
async def list_activities(
    plan_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: PlansServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    plan = await service.get_plan(plan_id=plan_id)
    if not has_capability(context, "plan.read", farm_id=plan["farm_id"]):
        raise PlanNotFoundError(plan_id)
    return list(await service.list_activities(plan_id=plan_id))


@router.patch(
    "/activities/{activity_id}",
    response_model=ActivityResponse,
    summary="Edit activity metadata or run a state transition.",
)
async def update_activity(
    activity_id: UUID,
    payload: ActivityUpdateRequest,
    context: RequestContext = Depends(get_current_context),
    service: PlansServiceImpl = Depends(_service),
) -> dict[str, Any]:
    from app.modules.plans.errors import ActivityNotFoundError

    schema = _ensure_tenant(context)
    # Fetch first so we know the activity's plan and through it the farm.
    activity = await service._repo.get_activity(activity_id=activity_id)
    if activity is None:
        raise ActivityNotFoundError(activity_id)
    plan = await service.get_plan(plan_id=activity["plan_id"])

    state_action = payload.state
    metadata_changes = payload.model_dump(exclude={"state"}, exclude_unset=True)

    # State transitions and metadata edits gate on different capabilities:
    #   * `complete` / `skip` (and `start` as the same flow's prelude) →
    #     `plan_activity.complete` so field operators can drive them.
    #   * Editing scheduled_date / product / dosage / notes → `plan.manage`
    #     so only managers reshuffle the schedule.
    if state_action is not None and not has_capability(
        context, "plan_activity.complete", farm_id=plan["farm_id"]
    ):
        raise ActivityNotFoundError(activity_id)
    if metadata_changes and not has_capability(context, "plan.manage", farm_id=plan["farm_id"]):
        raise ActivityNotFoundError(activity_id)

    return await service.update_activity(
        activity_id=activity_id,
        metadata_changes=metadata_changes,
        state_action=state_action,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
