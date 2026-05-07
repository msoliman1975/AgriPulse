"""FastAPI routes for the weather module.

Mounted under /api/v1 by the app factory. Endpoints:

  POST   /blocks/{block_id}/weather/subscriptions
  GET    /blocks/{block_id}/weather/subscriptions
  DELETE /blocks/{block_id}/weather/subscriptions/{subscription_id}
  POST   /blocks/{block_id}/weather/refresh

The observations / forecasts / derived-daily read endpoints land in
PR-C alongside the derivations.

RBAC mirrors imagery: block-only routes resolve the farm via the
repository, then call `has_capability(..., farm_id=...)` manually.
A capability denial surfaces as 404 to avoid leaking block existence
across farm scopes.

Note: deliberately NO `from __future__ import annotations` (same
reason as imagery/router.py — FastAPI's TypeAdapter cannot resolve
string annotations on Request injection).
"""

from datetime import date as date_type
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.weather.errors import BlockNotVisibleError
from app.modules.weather.repository import WeatherRepository
from app.modules.weather.schemas import (
    DerivedDailyRead,
    ForecastResponse,
    HourlyObservationRead,
    RefreshResponse,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.modules.weather.service import WeatherServiceImpl, get_weather_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1", tags=["weather"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> WeatherServiceImpl:
    return get_weather_service(tenant_session=tenant_session)


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
    """Look up the farm_id that owns this block; 404 if missing."""
    repo = WeatherRepository(tenant_session)
    block = await repo.get_block_farm_centroid(block_id)
    if block is None:
        raise BlockNotVisibleError(str(block_id))
    return block["farm_id"]


# --- Subscriptions ---------------------------------------------------------


@router.post(
    "/blocks/{block_id}/weather/subscriptions",
    response_model=SubscriptionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe a block to a weather provider.",
)
async def create_subscription(
    block_id: UUID,
    payload: SubscriptionCreate,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> SubscriptionRead:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.create_subscription(
        block_id=block_id,
        payload=payload,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/blocks/{block_id}/weather/subscriptions",
    response_model=list[SubscriptionRead],
    summary="List a block's weather subscriptions.",
)
async def list_subscriptions(
    block_id: UUID,
    include_inactive: bool = False,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> list[SubscriptionRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.list_subscriptions(block_id=block_id, include_inactive=include_inactive)
    return list(rows)


@router.delete(
    "/blocks/{block_id}/weather/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a weather subscription.",
)
async def revoke_subscription(
    block_id: UUID,
    subscription_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.subscription.manage", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    await service.revoke_subscription(
        block_id=block_id,
        subscription_id=subscription_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


# --- Refresh --------------------------------------------------------------


@router.post(
    "/blocks/{block_id}/weather/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger weather fetch now.",
)
async def trigger_refresh(
    block_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.refresh", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    cid = _correlation_id(request)
    queued = await service.trigger_refresh(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=cid,
    )
    return {
        "queued_farm_ids": queued,
        "correlation_id": str(cid) if cid else None,
    }


# --- Reads ----------------------------------------------------------------


@router.get(
    "/blocks/{block_id}/weather/forecast",
    response_model=ForecastResponse,
    summary="Daily-aggregated forecast in the farm's local timezone.",
)
async def get_forecast(
    block_id: UUID,
    horizon_days: int = Query(default=5, ge=1, le=10),
    provider_code: str = Query(default="open_meteo"),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> ForecastResponse:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    return await service.get_forecast(
        block_id=block_id,
        horizon_days=horizon_days,
        provider_code=provider_code,
    )


@router.get(
    "/blocks/{block_id}/weather/observations",
    response_model=list[HourlyObservationRead],
    summary="Hourly observations in [since, until).",
)
async def list_observations(
    block_id: UUID,
    since: datetime = Query(...),
    until: datetime = Query(...),
    provider_code: str | None = Query(default=None),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> list[HourlyObservationRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.get_observations(
        block_id=block_id,
        since=since,
        until=until,
        provider_code=provider_code,
    )
    return list(rows)


@router.get(
    "/blocks/{block_id}/weather/derived",
    response_model=list[DerivedDailyRead],
    summary="Daily derived weather signals (GDD, ET₀, rolling rainfall).",
)
async def list_derived_daily(
    block_id: UUID,
    since: date_type = Query(...),
    until: date_type = Query(...),
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
    service: WeatherServiceImpl = Depends(_service),
) -> list[DerivedDailyRead]:
    _ensure_tenant(context)
    farm_id = await _resolve_farm_id(block_id=block_id, tenant_session=tenant_session)
    if not has_capability(context, "weather.read", farm_id=farm_id):
        raise BlockNotVisibleError(str(block_id))
    rows = await service.get_derived_daily(
        block_id=block_id,
        since=since,
        until=until,
    )
    return list(rows)
