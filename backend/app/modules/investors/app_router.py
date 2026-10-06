"""Routes for the signed-in investor. Read-only, and only their own rows.

Mounted under /api/v1:

  GET /investor/me                       investor_app.use
  GET /investor/holdings                 investor_app.use
  GET /investor/holdings/{holding_id}    investor_app.use

The caller never names an investor: the row is found from the token's user.
A holding the investor does not own answers 404, the same as a missing one.

The response models are allowlists (see `InvestorApp*Response`). They carry
no share, no other holdings, no notes, no contract numbers and nothing about
farm health. `tests/unit/modules/investors` pins the exact field sets.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.investors.router import _ensure_tenant
from app.modules.investors.schemas import (
    InvestorAppHoldingResponse,
    InvestorAppMeResponse,
)
from app.modules.investors.service import InvestorsService, get_investors_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/investor", tags=["investor-app"])


def _service(
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> InvestorsService:
    _ensure_tenant(context)
    return get_investors_service(tenant_session=tenant_session, tenant_schema=context.tenant_schema)


@router.get("/me", response_model=InvestorAppMeResponse)
async def investor_me(
    context: RequestContext = Depends(requires_capability("investor_app.use")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.app_me(user_id=context.user_id)


@router.get("/holdings", response_model=list[InvestorAppHoldingResponse])
async def investor_holdings(
    context: RequestContext = Depends(requires_capability("investor_app.use")),
    service: InvestorsService = Depends(_service),
) -> list[dict[str, Any]]:
    return await service.app_holdings(user_id=context.user_id)


@router.get("/holdings/{holding_id}", response_model=InvestorAppHoldingResponse)
async def investor_holding(
    holding_id: UUID,
    context: RequestContext = Depends(requires_capability("investor_app.use")),
    service: InvestorsService = Depends(_service),
) -> dict[str, Any]:
    return await service.app_holding(user_id=context.user_id, holding_id=holding_id)
