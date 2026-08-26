"""Farm Timeline HTTP surface — one read endpoint.

Mounted under ``/api/v1/farms`` so the frontend builds the URL from the
farm id it already has, the way the insights routes do.

The route is gated on ``farm.read``, not on the seven capabilities behind
it. Gating on all seven would 403 the whole screen for a Scout, who holds
farm scopes and no tenant role; the service drops the kinds the caller
cannot read and names them in ``omitted_kinds`` instead, so the UI can say
"you cannot see alerts" rather than showing an empty lane that reads as
"nothing happened".
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_db_session
from app.shared.rbac.check import requires_capability

from .schemas import TimelineResponse
from .service import MAX_WINDOW_DAYS, TimelineService, get_timeline_service

router = APIRouter(prefix="/api/v1", tags=["timeline"])

# Default window when the caller sends neither bound: the last 90 days.
# Long enough to hold a season's worth of passes at Sentinel-2's ~5-day
# cadence, short enough to render without the row caps biting.
DEFAULT_WINDOW_DAYS = 90


def _service(session: AsyncSession = Depends(get_db_session)) -> TimelineService:
    return get_timeline_service(session)


def _ensure_tenant(context: RequestContext) -> None:
    if context.tenant_schema is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )


@router.get(
    "/farms/{farm_id}/timeline",
    response_model=TimelineResponse,
    response_model_by_alias=True,
    summary="Every datapoint on a farm (or one block), bucketed by calendar day.",
)
async def get_farm_timeline(
    farm_id: UUID,
    from_date: date | None = Query(
        default=None,
        alias="from",
        description="First calendar day, inclusive. Defaults to 90 days before `to`.",
    ),
    to_date: date | None = Query(
        default=None,
        alias="to",
        description="Last calendar day, inclusive. Defaults to today (UTC).",
    ),
    block_id: UUID | None = Query(
        default=None,
        description="Narrow to one block. Phenology stage transitions are returned "
        "ONLY in this mode — blocks on one farm run different plans, so a "
        "farm-wide stage would be untrue about all but one of them.",
    ),
    context: RequestContext = Depends(requires_capability("farm.read", farm_id_param="farm_id")),
    service: TimelineService = Depends(_service),
) -> TimelineResponse:
    _ensure_tenant(context)

    # Today in UTC, matching the day buckets the repository computes. Local
    # "today" on a pod in another zone would silently shift the window.
    resolved_to = to_date or date.today()
    resolved_from = from_date or (resolved_to - timedelta(days=DEFAULT_WINDOW_DAYS))

    if resolved_from > resolved_to:
        raise APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid window",
            detail="`from` must be on or before `to`.",
            type_="https://agripulse.cloud/problems/invalid-window",
        )
    span = (resolved_to - resolved_from).days + 1
    if span > MAX_WINDOW_DAYS:
        raise APIError(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Window too wide",
            detail=f"The window spans {span} days; the maximum is {MAX_WINDOW_DAYS}.",
            type_="https://agripulse.cloud/problems/window-too-wide",
        )

    if block_id is not None:
        # The capability check gated on farm_id. Without this, a block id
        # from another farm would be read through a farm the caller does
        # have access to.
        belongs = await service.block_belongs_to_farm(farm_id=farm_id, block_id=block_id)
        if not belongs:
            raise APIError(
                status_code=status.HTTP_404_NOT_FOUND,
                title="Block not found",
                detail="No such block on this farm.",
                type_="https://agripulse.cloud/problems/block-not-found",
            )

    return await service.get_timeline(
        farm_id=farm_id,
        block_id=block_id,
        from_date=resolved_from,
        to_date=resolved_to,
        context=context,
    )
