"""Action Center routes — the unified queue and its dispatch.

Mounted under /api/v1 by the app factory:

  GET  /action-items            — unified, filtered, grouped queue
  POST /action-items:dispatch   — assign items to a member as board activities

RBAC: reads need BOTH ``recommendation.read`` and ``alert.read`` — the response
mixes the two, so holding one capability must not leak the other's rows. A
caller with only one gets their half via ``kinds``.

Dispatch writes a board activity and therefore needs ``plan.manage`` on top of
``recommendation.act``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.action_center.schemas import (
    ActionItemListResponse,
    DispatchRequest,
    DispatchResponse,
)
from app.modules.action_center.service import (
    ActionCenterServiceImpl,
    get_action_center_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["action-center"])

# Named windows the UI offers. `custom` is expressed by passing explicit
# raised_from / raised_to instead.
_RANGES = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> ActionCenterServiceImpl:
    return get_action_center_service(tenant_session=tenant_session)


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


def _forbidden(detail: str) -> APIError:
    return APIError(
        status_code=status.HTTP_403_FORBIDDEN,
        title="Forbidden",
        detail=detail,
        type_="https://agripulse.cloud/problems/forbidden",
    )


@router.get(
    "/action-items",
    response_model=ActionItemListResponse,
    summary="Unified recommendations + alerts queue for a farm.",
)
async def list_action_items(
    farm_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: ActionCenterServiceImpl = Depends(_service),
    status_filter: Annotated[
        Literal["needs_action", "dispatched", "done", "dismissed", "all"] | None,
        Query(alias="status"),
    ] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    block_id: UUID | None = None,
    action_type: Annotated[list[str] | None, Query()] = None,
    severity: Annotated[list[str] | None, Query()] = None,
    assigned_membership_id: UUID | None = None,
    date_range: Annotated[Literal["1d", "7d", "30d", "90d", "all"] | None, Query()] = None,
    raised_from: datetime | None = None,
    raised_to: datetime | None = None,
    group_by: Annotated[Literal["none", "action_type", "block", "due"], Query()] = "action_type",
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> ActionItemListResponse:
    _ensure_tenant(context)
    can_rec = has_capability(context, "recommendation.read", farm_id=farm_id)
    can_alert = has_capability(context, "alert.read", farm_id=farm_id)
    if not can_rec and not can_alert:
        raise _forbidden("You cannot read recommendations or alerts on this farm.")

    kinds = tuple(kind or ())
    # Narrow to what the caller may actually see rather than filtering after
    # the query — a 403 on a mixed queue would be useless to a scout who holds
    # only one of the two capabilities.
    allowed = {k for k, ok in (("recommendation", can_rec), ("alert", can_alert)) if ok}
    kinds = tuple(k for k in kinds if k in allowed) if kinds else tuple(sorted(allowed))

    # A named range is sugar for raised_from; explicit bounds win so the
    # custom-range picker does not have to clear it first.
    if raised_from is None and date_range in _RANGES:
        raised_from = datetime.now(UTC) - timedelta(days=_RANGES[date_range])

    return await service.list_items(
        farm_id=farm_id,
        status=status_filter,
        kinds=kinds,
        block_id=block_id,
        action_types=tuple(action_type or ()),
        severities=tuple(severity or ()),
        assigned_membership_id=assigned_membership_id,
        raised_from=raised_from,
        raised_to=raised_to,
        group_by=group_by,
        limit=limit,
    )


@router.post(
    "/action-items:dispatch",
    response_model=DispatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign items to a team member as board activities.",
)
async def dispatch_action_items(
    farm_id: UUID,
    payload: DispatchRequest,
    context: RequestContext = Depends(get_current_context),
    service: ActionCenterServiceImpl = Depends(_service),
) -> DispatchResponse:
    schema = _ensure_tenant(context)
    if not has_capability(context, "plan.manage", farm_id=farm_id):
        raise _forbidden("Dispatching creates board activities, which needs plan.manage.")
    if not has_capability(context, "recommendation.act", farm_id=farm_id):
        raise _forbidden("You cannot act on recommendations for this farm.")

    return await service.dispatch(
        farm_id=farm_id,
        item_ids=payload.item_ids,
        assigned_membership_id=payload.assigned_membership_id,
        scheduled_date=payload.scheduled_date,
        notes=payload.notes,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
