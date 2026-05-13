"""Tenant integrations config endpoints â€” three tiers.

Mounted under /api/v1 by the app factory.

  GET    /integrations/weather/tenant
  PUT    /integrations/weather/tenant            { value: ... }       (per-key via ?key=)
  GET    /integrations/weather/farms/{farm_id}
  PUT    /integrations/weather/farms/{farm_id}   { provider_code, cadence_hours }

  GET    /integrations/imagery/tenant
  PUT    /integrations/imagery/tenant
  GET    /integrations/imagery/farms/{farm_id}
  PUT    /integrations/imagery/farms/{farm_id}   { product_code, cloud_cover_threshold_pct }
  PUT    /integrations/imagery/blocks/{block_id} { cloud_cover_max_pct }
  POST   /integrations/imagery/farms/{farm_id}:apply-to-blocks  { mode }

  GET    /integrations/email/tenant
  PUT    /integrations/email/tenant

  GET    /integrations/webhook/tenant
  PUT    /integrations/webhook/tenant

All gated on `tenant.manage_integrations` for writes,
`tenant.read_integration_health` (or its superset
`tenant.manage_integrations`) for reads. Reads also accept any user
with at least one of the two; the page itself does the strict check.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations.schemas import (
    ApplyToBlocksRequest,
    BlockImageryOverridePayload,
    FarmImageryOverridePayload,
    FarmWeatherOverridePayload,
    ResolvedIntegrationSetting,
    TenantIntegrationSettingsResponse,
    TenantSettingUpsertRequest,
)
from app.modules.integrations.service import (
    EMAIL_KEYS,
    IMAGERY_KEYS,
    IntegrationsService,
    WEATHER_KEYS,
    WEBHOOK_KEYS,
    get_integrations_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["integrations"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> IntegrationsService:
    return get_integrations_service(
        public_session=public_session, tenant_session=tenant_session
    )


def _ensure_tenant(context: RequestContext) -> tuple[UUID, str]:
    if context.tenant_id is None or context.tenant_schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return context.tenant_id, context.tenant_schema


# ---- Weather --------------------------------------------------------------


@router.get(
    "/integrations/weather/tenant",
    response_model=TenantIntegrationSettingsResponse,
)
async def get_weather_tenant(
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, _ = _ensure_tenant(context)
    return {"settings": await service.list_tenant(tenant_id=tid, keys=WEATHER_KEYS)}


@router.put(
    "/integrations/weather/tenant",
    response_model=ResolvedIntegrationSetting,
)
async def put_weather_tenant(
    payload: TenantSettingUpsertRequest,
    key: str = Query(..., description="The platform_defaults key to override."),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    if key not in WEATHER_KEYS:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid key",
            detail=f"{key!r} is not a weather-category key.",
            type_="https://agripulse.cloud/problems/integrations/invalid-key",
        )
    return await service.upsert_tenant_value(
        tenant_id=tid,
        key=key,
        value=payload.value,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.delete(
    "/integrations/weather/tenant",
    response_model=ResolvedIntegrationSetting,
    status_code=status.HTTP_200_OK,
)
async def delete_weather_tenant(
    key: str = Query(...),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    return await service.delete_tenant_value(
        tenant_id=tid,
        key=key,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.get(
    "/integrations/weather/farms/{farm_id}",
    response_model=TenantIntegrationSettingsResponse,
)
async def get_weather_farm(
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, _ = _ensure_tenant(context)
    return {
        "settings": await service.get_farm_weather(tenant_id=tid, farm_id=farm_id)
    }


@router.put(
    "/integrations/weather/farms/{farm_id}",
    response_model=TenantIntegrationSettingsResponse,
)
async def put_weather_farm(
    farm_id: UUID,
    payload: FarmWeatherOverridePayload,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    return {
        "settings": await service.upsert_farm_weather(
            tenant_id=tid,
            farm_id=farm_id,
            provider_code=payload.provider_code,
            cadence_hours=payload.cadence_hours,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    }


# ---- Imagery --------------------------------------------------------------


@router.get(
    "/integrations/imagery/tenant",
    response_model=TenantIntegrationSettingsResponse,
)
async def get_imagery_tenant(
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, _ = _ensure_tenant(context)
    return {"settings": await service.list_tenant(tenant_id=tid, keys=IMAGERY_KEYS)}


@router.put(
    "/integrations/imagery/tenant",
    response_model=ResolvedIntegrationSetting,
)
async def put_imagery_tenant(
    payload: TenantSettingUpsertRequest,
    key: str = Query(...),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    if key not in IMAGERY_KEYS:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid key",
            detail=f"{key!r} is not an imagery-category key.",
            type_="https://agripulse.cloud/problems/integrations/invalid-key",
        )
    return await service.upsert_tenant_value(
        tenant_id=tid,
        key=key,
        value=payload.value,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.delete(
    "/integrations/imagery/tenant",
    response_model=ResolvedIntegrationSetting,
)
async def delete_imagery_tenant(
    key: str = Query(...),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    return await service.delete_tenant_value(
        tenant_id=tid,
        key=key,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.get(
    "/integrations/imagery/farms/{farm_id}",
    response_model=TenantIntegrationSettingsResponse,
)
async def get_imagery_farm(
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, _ = _ensure_tenant(context)
    return {"settings": await service.get_farm_imagery(tenant_id=tid, farm_id=farm_id)}


@router.put(
    "/integrations/imagery/farms/{farm_id}",
    response_model=TenantIntegrationSettingsResponse,
)
async def put_imagery_farm(
    farm_id: UUID,
    payload: FarmImageryOverridePayload,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    return {
        "settings": await service.upsert_farm_imagery(
            tenant_id=tid,
            farm_id=farm_id,
            product_code=payload.product_code,
            cloud_cover_threshold_pct=payload.cloud_cover_threshold_pct,
            actor_user_id=context.user_id,
            tenant_schema=schema,
        )
    }


@router.put(
    "/integrations/imagery/blocks/{block_id}",
)
async def put_imagery_block(
    block_id: UUID,
    payload: BlockImageryOverridePayload,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    _, schema = _ensure_tenant(context)
    return await service.upsert_block_imagery(
        block_id=block_id,
        cloud_cover_max_pct=payload.cloud_cover_max_pct,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.post(
    "/integrations/imagery/farms/{farm_id}:apply-to-blocks",
)
async def apply_imagery_to_blocks(
    farm_id: UUID,
    payload: ApplyToBlocksRequest,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    _, schema = _ensure_tenant(context)
    return await service.apply_to_blocks(
        farm_id=farm_id,
        mode=payload.mode,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---- Email ----------------------------------------------------------------


@router.get(
    "/integrations/email/tenant",
    response_model=TenantIntegrationSettingsResponse,
)
async def get_email_tenant(
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, _ = _ensure_tenant(context)
    return {"settings": await service.list_tenant(tenant_id=tid, keys=EMAIL_KEYS)}


@router.put(
    "/integrations/email/tenant",
    response_model=ResolvedIntegrationSetting,
)
async def put_email_tenant(
    payload: TenantSettingUpsertRequest,
    key: str = Query(...),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    if key not in EMAIL_KEYS:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid key",
            detail=f"{key!r} is not an email-category key.",
            type_="https://agripulse.cloud/problems/integrations/invalid-key",
        )
    return await service.upsert_tenant_value(
        tenant_id=tid,
        key=key,
        value=payload.value,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---- Webhook --------------------------------------------------------------


@router.get(
    "/integrations/webhook/tenant",
    response_model=TenantIntegrationSettingsResponse,
)
async def get_webhook_tenant(
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, _ = _ensure_tenant(context)
    return {"settings": await service.list_tenant(tenant_id=tid, keys=WEBHOOK_KEYS)}


@router.put(
    "/integrations/webhook/tenant",
    response_model=ResolvedIntegrationSetting,
)
async def put_webhook_tenant(
    payload: TenantSettingUpsertRequest,
    key: str = Query(...),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    service: IntegrationsService = Depends(_service),
) -> dict[str, Any]:
    tid, schema = _ensure_tenant(context)
    if key not in WEBHOOK_KEYS:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid key",
            detail=f"{key!r} is not a webhook-category key.",
            type_="https://agripulse.cloud/problems/integrations/invalid-key",
        )
    return await service.upsert_tenant_value(
        tenant_id=tid,
        key=key,
        value=payload.value,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
