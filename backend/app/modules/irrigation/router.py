"""FastAPI routes for the irrigation module.

GET    /farms/{farm_id}/irrigation/schedules
POST   /blocks/{block_id}/irrigation/generate
PATCH  /irrigation/schedules/{schedule_id}
"""

from datetime import date as date_type
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.irrigation.errors import IrrigationScheduleNotFoundError
from app.modules.irrigation.schemas import (
    IrrigationApplyRequest,
    IrrigationGenerateRequest,
    IrrigationScheduleResponse,
)
from app.modules.irrigation.service import (
    IrrigationServiceImpl,
    get_irrigation_service,
)
from app.shared.auth.context import RequestContext
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


@router.post(
    "/blocks/{block_id}/irrigation/generate",
    response_model=IrrigationScheduleResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Generate (or refresh) the irrigation recommendation for a block.",
)
async def generate_for_block(
    block_id: UUID,
    payload: IrrigationGenerateRequest,
    context: RequestContext = Depends(requires_capability("irrigation.schedule.manage")),
    service: IrrigationServiceImpl = Depends(_service),
) -> dict[str, Any] | None:
    schema = _ensure_tenant(context)
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
    context: RequestContext = Depends(requires_capability("irrigation.schedule.manage")),
    service: IrrigationServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
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
