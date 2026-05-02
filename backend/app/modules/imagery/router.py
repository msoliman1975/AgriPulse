"""FastAPI routes for the imagery module.

Mounted under /api/v1 by the app factory. Endpoints:

  POST   /blocks/{block_id}/imagery/subscriptions
  GET    /blocks/{block_id}/imagery/subscriptions
  DELETE /blocks/{block_id}/imagery/subscriptions/{subscription_id}
  POST   /blocks/{block_id}/imagery/refresh

The list-scenes / index-timeseries / config endpoints land in PR-C.

Per-farm RBAC pattern (matching farms/router.py): block-only routes
take only the JWT context, then look up the block to learn which farm
it belongs to, then call `has_capability(..., farm_id=...)` manually.
A capability denial surfaces as 404 to avoid leaking block existence
across farm scopes.

Note: deliberately NO `from __future__ import annotations`. FastAPI/
Pydantic v2's TypeAdapter cannot resolve string annotations like
``request: Request`` and silently demotes them to required query
parameters, breaking POST validation.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imagery.errors import BlockNotVisibleError
from app.modules.imagery.repository import ImageryRepository
from app.modules.imagery.schemas import (
    RefreshResponse,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.modules.imagery.service import ImageryService, get_imagery_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["imagery"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> ImageryService:
    return get_imagery_service(tenant_session=tenant_session)


def _correlation_id(request: Request) -> UUID | None:
    cid = getattr(request.state, "correlation_id", None)
    if isinstance(cid, str):
        try:
            return UUID(cid)
        except ValueError:
            return None
    if isinstance(cid, UUID):
        return cid
    return None


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


async def _resolve_farm_id(*, block_id: UUID, tenant_session: AsyncSession) -> UUID:
    """Look up the farm_id that owns this block; 404 if missing.

    Used by every imagery endpoint to gate per-farm capabilities. Going
    through the repository keeps the cross-module read in one place
    (no SQL leaks into the router).
    """
    repo = ImageryRepository(tenant_session)
    block = await repo.get_block_boundary(block_id)
    if block is None:
        raise BlockNotVisibleError(str(block_id))
    return block["farm_id"]


# --- Subscriptions ---------------------------------------------------------


@router.post(
    "/blocks/{block_id}/imagery/subscriptions",
    response_model=SubscriptionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe a block to an imagery product.",
)
async def create_subscription(
    block_id: UUID,
    payload: SubscriptionCreate,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: ImageryService = Depends(_service),
) -> SubscriptionRead:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "imagery.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.create_subscription(
        block_id=block_id,
        payload=payload,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/blocks/{block_id}/imagery/subscriptions",
    response_model=list[SubscriptionRead],
    summary="List a block's imagery subscriptions.",
)
async def list_subscriptions(
    block_id: UUID,
    include_inactive: bool = False,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: ImageryService = Depends(_service),
) -> list[SubscriptionRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "imagery.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.list_subscriptions(block_id=block_id, include_inactive=include_inactive)
    return list(rows)


@router.delete(
    "/blocks/{block_id}/imagery/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a subscription.",
)
async def revoke_subscription(
    block_id: UUID,
    subscription_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: ImageryService = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "imagery.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    await service.revoke_subscription(
        subscription_id=subscription_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


# --- Refresh --------------------------------------------------------------


@router.post(
    "/blocks/{block_id}/imagery/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger imagery discovery now.",
)
async def trigger_refresh(
    block_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: ImageryService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "imagery.refresh", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    cid = _correlation_id(request)
    queued = await service.trigger_refresh(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=cid,
    )
    return {
        "queued_subscription_ids": queued,
        "correlation_id": str(cid) if cid else None,
    }
