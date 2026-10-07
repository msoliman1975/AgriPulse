"""Investor and holding routes for staff (the web app).

Mounted under /api/v1:

  GET    /investors                                   investor.read
  POST   /investors                                   investor.manage
  GET    /investors/{id}                              investor.read
  PATCH  /investors/{id}                              investor.manage
  POST   /investors/{id}:archive                      investor.manage
  POST   /investors/{id}:create-login                 investor.invite
  POST   /investors/{id}:resend-login                 investor.invite
  POST   /investors/{id}:disable-login                investor.invite
  POST   /investors/{id}:enable-login                 investor.invite

  GET    /farms/{farm_id}/investments/overview        holding.read
  GET    /farms/{farm_id}/investors                   investor.read
  GET    /farms/{farm_id}/holdings-map                holding.read

  GET    /farms/{farm_id}/holdings                    holding.read
  GET    /farms/{farm_id}/blocks/{block_id}/holdings  holding.read   (draw-screen context)
  POST   /farms/{farm_id}/blocks/{block_id}/holdings  holding.manage
  POST   /farms/{farm_id}/holdings                    holding.manage (block found)
  POST   /farms/{farm_id}/holdings:check              holding.read   (dry run)
  GET    /farms/{farm_id}/holdings/{id}               holding.read
  PATCH  /farms/{farm_id}/holdings/{id}               holding.manage (+ holding.redraw_sold)
  POST   /farms/{farm_id}/holdings/{id}:archive       holding.manage
  DELETE /farms/{farm_id}/holdings/{id}               holding.manage  (no ownership history)

  POST   /farms/{farm_id}/holdings/{id}/ownerships    holding.assign_owner
  POST   /farms/{farm_id}/ownerships/{id}:end         holding.assign_owner
  DELETE /farms/{farm_id}/ownerships/{id}             holding.assign_owner

Investors are tenant-wide, so their routes take no farm. Holdings belong to a
block, so their routes are farm-scoped and a farm-scoped grant works.

The investor reads through `app_router.py`. Nothing here is meant for an
investor token: the Investor role holds none of these capabilities.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.iam.users_service import TenantUsersService, get_tenant_users_service
from app.modules.investors.schemas import (
    BlockHoldingsContextResponse,
    FarmHoldingsMapResponse,
    FarmInvestorResponse,
    HoldingCheckRequest,
    HoldingCheckResult,
    HoldingCreateRequest,
    HoldingDetailResponse,
    HoldingResponse,
    HoldingUpdateRequest,
    InvestmentsOverviewResponse,
    InvestorCreateRequest,
    InvestorDetailResponse,
    InvestorLoginResponse,
    InvestorResponse,
    InvestorStatus,
    InvestorUpdateRequest,
    OwnershipCreateRequest,
    OwnershipEndRequest,
)
from app.modules.investors.service import InvestorsService, get_investors_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["investors"])


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


def _service(
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> InvestorsService:
    _ensure_tenant(context)
    return get_investors_service(tenant_session=tenant_session, tenant_schema=context.tenant_schema)


def _users(
    admin_session: AsyncSession = Depends(get_admin_db_session),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> TenantUsersService:
    return get_tenant_users_service(admin_session, tenant_session=tenant_session)


def _tenant_id(context: RequestContext) -> UUID:
    if context.tenant_id is None:
        _ensure_tenant(context)
        raise AssertionError("unreachable")
    return context.tenant_id


# ---- Investors ----------------------------------------------------------


@router.get("/investors", response_model=list[InvestorResponse])
async def list_investors(
    status_filter: InvestorStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100),
    include_archived: bool = Query(default=False),
    _: RequestContext = Depends(requires_capability("investor.read")),
    service: InvestorsService = Depends(_service),
) -> list[dict[str, Any]]:
    return await service.list_investors(
        status=status_filter, query=q, include_archived=include_archived
    )


@router.post("/investors", response_model=InvestorResponse, status_code=status.HTTP_201_CREATED)
async def create_investor(
    payload: InvestorCreateRequest,
    context: RequestContext = Depends(requires_capability("investor.manage")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.create_investor(
        fields=payload.model_dump(exclude_none=True), actor_user_id=context.user_id
    )


@router.get("/investors/{investor_id}", response_model=InvestorDetailResponse)
async def get_investor(
    investor_id: UUID,
    _: RequestContext = Depends(requires_capability("investor.read")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.get_investor_detail(investor_id=investor_id)


@router.patch("/investors/{investor_id}", response_model=InvestorResponse)
async def update_investor(
    investor_id: UUID,
    payload: InvestorUpdateRequest,
    context: RequestContext = Depends(requires_capability("investor.manage")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.update_investor(
        investor_id=investor_id,
        changes=payload.model_dump(exclude_unset=True),
        actor_user_id=context.user_id,
    )


@router.post("/investors/{investor_id}:archive", response_model=InvestorResponse)
async def archive_investor(
    investor_id: UUID,
    context: RequestContext = Depends(requires_capability("investor.manage")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.archive_investor(investor_id=investor_id, actor_user_id=context.user_id)


# ---- Holdings -----------------------------------------------------------


@router.get("/farms/{farm_id}/holdings", response_model=list[HoldingResponse])
async def list_farm_holdings(
    farm_id: UUID,
    block_id: UUID | None = Query(default=None),
    include_archived: bool = Query(default=False),
    _: RequestContext = Depends(requires_capability("holding.read", farm_id_param="farm_id")),
    service: InvestorsService = Depends(_service),
) -> list[dict[str, Any]]:
    return await service.list_holdings(
        farm_id=farm_id, block_id=block_id, include_archived=include_archived
    )


@router.get(
    "/farms/{farm_id}/blocks/{block_id}/holdings",
    response_model=BlockHoldingsContextResponse,
)
async def block_holdings_context(
    farm_id: UUID,
    block_id: UUID,
    _: RequestContext = Depends(requires_capability("holding.read", farm_id_param="farm_id")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.block_context(farm_id=farm_id, block_id=block_id)


@router.post(
    "/farms/{farm_id}/blocks/{block_id}/holdings",
    response_model=HoldingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_holding(
    farm_id: UUID,
    block_id: UUID,
    payload: HoldingCreateRequest,
    context: RequestContext = Depends(
        requires_capability("holding.manage", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.create_holding(
        farm_id=farm_id,
        block_id=block_id,
        payload=payload.model_dump(),
        actor_user_id=context.user_id,
    )


@router.post(
    "/farms/{farm_id}/holdings",
    response_model=HoldingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_farm_holding(
    farm_id: UUID,
    payload: HoldingCreateRequest,
    context: RequestContext = Depends(
        requires_capability("holding.manage", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    """Create a holding from a drawn or uploaded shape; the block is found."""
    return await service.create_holding(
        farm_id=farm_id,
        block_id=payload.block_id,
        payload=payload.model_dump(),
        actor_user_id=context.user_id,
    )


@router.post("/farms/{farm_id}/holdings:check", response_model=list[HoldingCheckResult])
async def check_holding_shapes(
    farm_id: UUID,
    payload: HoldingCheckRequest,
    _: RequestContext = Depends(requires_capability("holding.read", farm_id_param="farm_id")),
    service: InvestorsService = Depends(_service),
) -> list[dict[str, Any]]:
    """For each shape: the block that fully contains it, or why none does."""
    return [await service.check_shape(farm_id=farm_id, boundary=b) for b in payload.boundaries]


@router.get("/farms/{farm_id}/holdings/{holding_id}", response_model=HoldingDetailResponse)
async def get_holding(
    farm_id: UUID,
    holding_id: UUID,
    _: RequestContext = Depends(requires_capability("holding.read", farm_id_param="farm_id")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.get_holding_detail(farm_id=farm_id, holding_id=holding_id)


@router.patch("/farms/{farm_id}/holdings/{holding_id}", response_model=HoldingResponse)
async def update_holding(
    farm_id: UUID,
    holding_id: UUID,
    payload: HoldingUpdateRequest,
    context: RequestContext = Depends(
        requires_capability("holding.manage", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.update_holding(
        farm_id=farm_id,
        holding_id=holding_id,
        changes=payload.model_dump(exclude_unset=True),
        can_redraw_sold=has_capability(context, "holding.redraw_sold", farm_id=farm_id),
        actor_user_id=context.user_id,
    )


@router.post("/farms/{farm_id}/holdings/{holding_id}:archive", response_model=HoldingResponse)
async def archive_holding(
    farm_id: UUID,
    holding_id: UUID,
    context: RequestContext = Depends(
        requires_capability("holding.manage", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.archive_holding(
        farm_id=farm_id, holding_id=holding_id, actor_user_id=context.user_id
    )


@router.delete(
    "/farms/{farm_id}/holdings/{holding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_holding(
    farm_id: UUID,
    holding_id: UUID,
    context: RequestContext = Depends(
        requires_capability("holding.manage", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> None:
    await service.delete_holding(
        farm_id=farm_id, holding_id=holding_id, actor_user_id=context.user_id
    )


# ---- Ownership ----------------------------------------------------------


@router.post(
    "/farms/{farm_id}/holdings/{holding_id}/ownerships",
    response_model=HoldingDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_owner(
    farm_id: UUID,
    holding_id: UUID,
    payload: OwnershipCreateRequest,
    context: RequestContext = Depends(
        requires_capability("holding.assign_owner", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.assign_owner(
        farm_id=farm_id,
        holding_id=holding_id,
        payload=payload.model_dump(),
        actor_user_id=context.user_id,
    )


@router.post("/farms/{farm_id}/ownerships/{ownership_id}:end", response_model=HoldingDetailResponse)
async def end_ownership(
    farm_id: UUID,
    ownership_id: UUID,
    payload: OwnershipEndRequest,
    context: RequestContext = Depends(
        requires_capability("holding.assign_owner", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.end_ownership(
        farm_id=farm_id,
        ownership_id=ownership_id,
        end_date=payload.end_date,
        ended_by=payload.ended_by,
        actor_user_id=context.user_id,
    )


@router.delete(
    "/farms/{farm_id}/ownerships/{ownership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_ownership(
    farm_id: UUID,
    ownership_id: UUID,
    context: RequestContext = Depends(
        requires_capability("holding.assign_owner", farm_id_param="farm_id")
    ),
    service: InvestorsService = Depends(_service),
) -> Response:
    await service.delete_ownership(
        farm_id=farm_id, ownership_id=ownership_id, actor_user_id=context.user_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- App login ----------------------------------------------------------


@router.post("/investors/{investor_id}:create-login", response_model=InvestorLoginResponse)
async def create_investor_login(
    investor_id: UUID,
    context: RequestContext = Depends(requires_capability("investor.invite")),
    service: InvestorsService = Depends(_service),
    users: TenantUsersService = Depends(_users),
) -> dict[str, Any]:
    return await service.create_login(
        investor_id=investor_id, users=users, actor_user_id=context.user_id
    )


@router.post("/investors/{investor_id}:resend-login", response_model=InvestorLoginResponse)
async def resend_investor_login(
    investor_id: UUID,
    context: RequestContext = Depends(requires_capability("investor.invite")),
    service: InvestorsService = Depends(_service),
    users: TenantUsersService = Depends(_users),
) -> dict[str, Any]:
    return await service.resend_login(
        investor_id=investor_id,
        users=users,
        tenant_id=_tenant_id(context),
        actor_user_id=context.user_id,
    )


@router.post("/investors/{investor_id}:disable-login", response_model=InvestorResponse)
async def disable_investor_login(
    investor_id: UUID,
    context: RequestContext = Depends(requires_capability("investor.invite")),
    service: InvestorsService = Depends(_service),
    users: TenantUsersService = Depends(_users),
) -> dict[str, Any]:
    return await service.set_login_enabled(
        investor_id=investor_id,
        enabled=False,
        users=users,
        tenant_id=_tenant_id(context),
        actor_user_id=context.user_id,
    )


@router.post("/investors/{investor_id}:enable-login", response_model=InvestorResponse)
async def enable_investor_login(
    investor_id: UUID,
    context: RequestContext = Depends(requires_capability("investor.invite")),
    service: InvestorsService = Depends(_service),
    users: TenantUsersService = Depends(_users),
) -> dict[str, Any]:
    return await service.set_login_enabled(
        investor_id=investor_id,
        enabled=True,
        users=users,
        tenant_id=_tenant_id(context),
        actor_user_id=context.user_id,
    )


# ---- Investments overview and farm map ----------------------------------


@router.get("/farms/{farm_id}/investments/overview", response_model=InvestmentsOverviewResponse)
async def investments_overview(
    farm_id: UUID,
    _: RequestContext = Depends(requires_capability("holding.read", farm_id_param="farm_id")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.overview(farm_id=farm_id)


@router.get("/farms/{farm_id}/investors", response_model=list[FarmInvestorResponse])
async def list_farm_investors(
    farm_id: UUID,
    status_filter: InvestorStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100),
    include_archived: bool = Query(default=False),
    _: RequestContext = Depends(requires_capability("investor.read")),
    service: InvestorsService = Depends(_service),
) -> list[dict[str, Any]]:
    return await service.list_investors_for_farm(
        farm_id=farm_id, status=status_filter, query=q, include_archived=include_archived
    )


@router.get("/farms/{farm_id}/holdings-map", response_model=FarmHoldingsMapResponse)
async def farm_holdings_map(
    farm_id: UUID,
    _: RequestContext = Depends(requires_capability("holding.read", farm_id_param="farm_id")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.farm_map(farm_id=farm_id)
