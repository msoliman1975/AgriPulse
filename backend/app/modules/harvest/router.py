"""Harvest records routes (build plan 3.5).

  GET    /api/v1/blocks/{block_id}/harvest-lots       harvest.read
  POST   /api/v1/blocks/{block_id}/harvest-lots       harvest.manage
  PATCH  /api/v1/harvest-lots/{lot_id}                harvest.manage
  DELETE /api/v1/harvest-lots/{lot_id}                harvest.manage

Capabilities are checked on the block's farm. A caller without them gets the
same 404 as for a missing block or pick, so ids cannot be probed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.harvest.schemas import (
    HarvestLotCreateRequest,
    HarvestLotResponse,
    HarvestLotUpdateRequest,
)
from app.modules.harvest.service import (
    HarvestBlockNotFoundError,
    HarvestLotNotFoundError,
    HarvestLotRejectedError,
    HarvestService,
    get_harvest_service,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["harvest"])


def _problem(code: int, title: str, detail: str, slug: str) -> APIError:
    return APIError(
        status_code=code,
        title=title,
        detail=detail,
        type_=f"https://agripulse.cloud/problems/{slug}",
    )


def _service(
    context: RequestContext = Depends(get_current_context),
    session: AsyncSession = Depends(get_db_session),
) -> HarvestService:
    if context.tenant_schema is None:
        raise _problem(
            status.HTTP_403_FORBIDDEN,
            "Tenant context required",
            "This endpoint requires a tenant-scoped JWT.",
            "tenant-required",
        )
    return get_harvest_service(tenant_session=session, tenant_schema=context.tenant_schema)


def _block_not_found(block_id: UUID) -> APIError:
    return _problem(
        status.HTTP_404_NOT_FOUND,
        "Block not found",
        f"No block with id {block_id} in this tenant.",
        "block-not-found",
    )


def _lot_not_found(lot_id: UUID) -> APIError:
    return _problem(
        status.HTTP_404_NOT_FOUND,
        "Harvest pick not found",
        f"No harvest pick with id {lot_id}.",
        "harvest-lot-not-found",
    )


def _rejected(exc: Exception) -> APIError:
    return _problem(
        status.HTTP_409_CONFLICT, "Harvest pick not accepted", str(exc), "harvest-lot-rejected"
    )


async def _farm_or_404(
    service: HarvestService, context: RequestContext, block_id: UUID, capability: str
) -> UUID:
    try:
        farm_id = await service.farm_for_block(block_id)
    except HarvestBlockNotFoundError as exc:
        raise _block_not_found(block_id) from exc
    if not has_capability(context, capability, farm_id=farm_id):
        raise _block_not_found(block_id)
    return farm_id


async def _lot_or_404(
    service: HarvestService, context: RequestContext, lot_id: UUID, capability: str
) -> dict[str, Any]:
    try:
        lot = await service.get(lot_id)
    except HarvestLotNotFoundError as exc:
        raise _lot_not_found(lot_id) from exc
    if not has_capability(context, capability, farm_id=lot["farm_id"]):
        raise _lot_not_found(lot_id)
    return lot


@router.get("/blocks/{block_id}/harvest-lots", response_model=list[HarvestLotResponse])
async def list_harvest_lots(
    block_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: HarvestService = Depends(_service),
) -> list[dict[str, Any]]:
    await _farm_or_404(service, context, block_id, "harvest.read")
    return await service.list_for_block(block_id)


@router.post(
    "/blocks/{block_id}/harvest-lots",
    response_model=HarvestLotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_harvest_lot(
    block_id: UUID,
    payload: HarvestLotCreateRequest,
    context: RequestContext = Depends(get_current_context),
    service: HarvestService = Depends(_service),
) -> dict[str, Any]:
    await _farm_or_404(service, context, block_id, "harvest.manage")
    try:
        return await service.create(
            block_id=block_id,
            tenant_id=context.tenant_id,
            fields=payload.model_dump(),
            actor_user_id=context.user_id,
        )
    except HarvestLotRejectedError as exc:
        raise _rejected(exc) from exc


@router.patch("/harvest-lots/{lot_id}", response_model=HarvestLotResponse)
async def update_harvest_lot(
    lot_id: UUID,
    payload: HarvestLotUpdateRequest,
    context: RequestContext = Depends(get_current_context),
    service: HarvestService = Depends(_service),
) -> dict[str, Any]:
    await _lot_or_404(service, context, lot_id, "harvest.manage")
    try:
        return await service.update(
            lot_id=lot_id,
            changes=payload.model_dump(exclude_unset=True),
            actor_user_id=context.user_id,
        )
    except HarvestLotRejectedError as exc:
        raise _rejected(exc) from exc
    except HarvestLotNotFoundError as exc:
        raise _lot_not_found(lot_id) from exc


@router.delete(
    "/harvest-lots/{lot_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_harvest_lot(
    lot_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: HarvestService = Depends(_service),
) -> Response:
    await _lot_or_404(service, context, lot_id, "harvest.manage")
    try:
        await service.delete(lot_id=lot_id, actor_user_id=context.user_id)
    except HarvestLotNotFoundError as exc:
        raise _lot_not_found(lot_id) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
