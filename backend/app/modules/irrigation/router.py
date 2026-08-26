"""FastAPI routes for the irrigation module.

GET    /farms/{farm_id}/irrigation/schedules
POST   /blocks/{block_id}/irrigation/generate
PATCH  /irrigation/schedules/{schedule_id}
"""

from datetime import date as date_type
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.irrigation.errors import (
    IrrigationScheduleNotFoundError,
    IrrigationTargetNotFoundError,
)
from app.modules.irrigation.schemas import (
    IrrigationApplyRequest,
    IrrigationGenerateRequest,
    IrrigationScheduleResponse,
    WaterBalanceDayResponse,
)
from app.modules.irrigation.service import (
    IrrigationServiceImpl,
    get_irrigation_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["irrigation"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> IrrigationServiceImpl:
    return get_irrigation_service(tenant_session=tenant_session, public_session=public_session)


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


@router.get(
    "/farms/{farm_id}/irrigation/schedules",
    response_model=list[IrrigationScheduleResponse],
    summary="List irrigation recommendations for a farm.",
)
async def list_for_farm(
    farm_id: UUID,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    context: RequestContext = Depends(
        requires_capability("irrigation.schedule.read", farm_id_param="farm_id")
    ),
    service: IrrigationServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    rows = await service.list_for_farm(
        farm_id=farm_id,
        from_date=from_date,
        to_date=to_date,
        status_filter=tuple(status_filter or ()),
    )
    return list(rows)


async def _require_on_farm(
    context: RequestContext,
    capability: str,
    farm_id: UUID | None,
    *,
    kind: str,
    target_id: UUID,
) -> None:
    """Check `capability` against the farm the addressed row lives in.

    These three routes are keyed on a block or a schedule, not a farm, so
    `requires_capability(farm_id_param=...)` has nothing to read and the
    resolver never reaches the farm tier. That denied every farm-scoped
    caller: an Agronomist could not generate an irrigation schedule for a
    block on their own farm.

    404 rather than 403 on failure, matching the block routes in
    `farms/router`: the id is in the path, and answering "forbidden" tells a
    caller which ids exist on farms they cannot see.
    """
    if farm_id is None or not has_capability(context, capability, farm_id=farm_id):
        raise IrrigationTargetNotFoundError(kind, target_id)


@router.get(
    "/blocks/{block_id}/water-balance",
    response_model=list[WaterBalanceDayResponse],
    summary="Daily crop water balance for one block.",
)
async def list_water_balance(
    block_id: UUID,
    from_date: date_type | None = Query(default=None, alias="from"),
    to_date: date_type | None = Query(default=None, alias="to"),
    context: RequestContext = Depends(get_current_context),
    service: IrrigationServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    """Oldest first, so the caller charts it without re-sorting.

    Defaults to the trailing 30 days — long enough to read a trend, short
    enough that the dock does not pull a season on open. Gated on
    `irrigation.schedule.read` rather than a new capability: this is the same
    irrigation data the schedule list already exposes, re-cut per day.
    """
    _ensure_tenant(context)
    await _require_on_farm(
        context,
        "irrigation.schedule.read",
        await service.farm_for_block(block_id=block_id),
        kind="block",
        target_id=block_id,
    )
    end = to_date or date_type.today()
    start = from_date or end - timedelta(days=30)
    rows = await service.list_water_balance(block_id=block_id, from_date=start, to_date=end)
    return list(rows)


@router.post(
    "/blocks/{block_id}/irrigation/generate",
    response_model=IrrigationScheduleResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Generate (or refresh) the irrigation recommendation for a block.",
)
async def generate_for_block(
    block_id: UUID,
    payload: IrrigationGenerateRequest,
    context: RequestContext = Depends(get_current_context),
    service: IrrigationServiceImpl = Depends(_service),
) -> dict[str, Any] | None:
    schema = _ensure_tenant(context)
    await _require_on_farm(
        context,
        "irrigation.schedule.manage",
        await service.farm_for_block(block_id=block_id),
        kind="block",
        target_id=block_id,
    )
    return await service.generate_for_block(
        block_id=block_id,
        scheduled_for=payload.scheduled_for,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.patch(
    "/irrigation/schedules/{schedule_id}",
    response_model=IrrigationScheduleResponse,
    summary="Apply or skip a pending irrigation recommendation.",
)
async def apply_or_skip(
    schedule_id: UUID,
    payload: IrrigationApplyRequest,
    context: RequestContext = Depends(get_current_context),
    service: IrrigationServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    await _require_on_farm(
        context,
        "irrigation.schedule.manage",
        await service.farm_for_schedule(schedule_id=schedule_id),
        kind="schedule",
        target_id=schedule_id,
    )
    if payload.action == "apply" and payload.applied_volume_mm is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Missing required field",
            detail="`applied_volume_mm` is required when action='apply'.",
            type_="https://agripulse.cloud/problems/irrigation-missing-volume",
        )
    return await service.transition(
        schedule_id=schedule_id,
        action=payload.action,
        applied_volume_mm=payload.applied_volume_mm,
        notes=payload.notes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# Suppress unused-import warnings.
_ = (IrrigationScheduleNotFoundError, has_capability)
