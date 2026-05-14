"""Platform-side per-tenant integration setup endpoints.

Mounted under /api/v1/admin/tenants/{tenant_id}/integrations/{category}.
PlatformAdmin only via `tenant.manage_integrations` (granted to
PlatformAdmin via the wildcard `*`).

Reads and writes the tenant tier of the three-tier resolver
(`public.tenant_settings_overrides`). Farm and LandUnit tier overrides
stay in AgriPulse â€” the Platform portal only sets the tenant
defaults that TenantOwner can later override.

Audit lands in `audit_events_archive` since these are platform-level
actions taken on a tenant's behalf.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import get_audit_service
from app.modules.integrations.service import (
    EMAIL_KEYS,
    IMAGERY_KEYS,
    WEATHER_KEYS,
    WEBHOOK_KEYS,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability
from app.shared.settings import (
    SettingsRepository,
    SettingsResolver,
    invalidate_defaults_cache,
)

router = APIRouter(
    prefix="/api/v1/admin/tenants/{tenant_id}/integrations",
    tags=["admin-tenant-integrations"],
)

Category = Literal["weather", "imagery", "email", "webhook"]

CATEGORY_KEYS: dict[Category, tuple[str, ...]] = {
    "weather": WEATHER_KEYS,
    "imagery": IMAGERY_KEYS,
    "email": EMAIL_KEYS,
    "webhook": WEBHOOK_KEYS,
}


class ResolvedSettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    source: str
    overridden_at: datetime | None = None


class TenantSettingsResponse(BaseModel):
    settings: list[ResolvedSettingResponse]


class TenantSettingUpsertBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any = Field(description="JSON value to store at the tenant tier.")


def _validate_category(category: str) -> Category:
    if category not in CATEGORY_KEYS:
        from app.core.errors import APIError

        raise APIError(
            status_code=400,
            title="Invalid integration category",
            detail=f"{category!r} is not one of {list(CATEGORY_KEYS)}",
            type_="https://agripulse.cloud/problems/integrations/invalid-category",
        )
    return category


@router.get(
    "/{category}",
    response_model=TenantSettingsResponse,
    summary="Read this tenant's integration tier values for a category.",
)
async def read_tenant_integration(
    tenant_id: UUID,
    category: str,
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    del context
    cat = _validate_category(category)
    resolver = SettingsResolver(public_session=public_session)
    out: list[dict[str, Any]] = []
    for key in CATEGORY_KEYS[cat]:
        resolved = await resolver.get_tenant(tenant_id, key)
        out.append(
            {
                "key": key,
                "value": resolved.value,
                "source": resolved.source,
                "overridden_at": resolved.overridden_at,
            }
        )
    return {"settings": out}


@router.put(
    "/{category}",
    response_model=ResolvedSettingResponse,
    summary="Set one tenant-tier value for this tenant.",
)
async def write_tenant_integration(
    tenant_id: UUID,
    category: str,
    payload: TenantSettingUpsertBody,
    key: str = Query(..., description="The platform_defaults key to override."),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    cat = _validate_category(category)
    if key not in CATEGORY_KEYS[cat]:
        from app.core.errors import APIError

        raise APIError(
            status_code=400,
            title="Invalid key for category",
            detail=f"{key!r} does not belong to category {cat!r}",
            type_="https://agripulse.cloud/problems/integrations/invalid-key",
        )

    repo = SettingsRepository(public_session=public_session)
    await repo.upsert_tenant_override(
        tenant_id=tenant_id,
        key=key,
        value_json=json.dumps(payload.value),
        actor_user_id=context.user_id,
    )
    invalidate_defaults_cache()

    audit = get_audit_service()
    await audit.record_archive(
        event_type="platform.tenant_integration_set",
        actor_user_id=context.user_id,
        subject_kind="tenant",
        subject_id=tenant_id,
        details={"key": key, "value": payload.value, "category": cat},
    )

    resolver = SettingsResolver(public_session=public_session)
    resolved = await resolver.get_tenant(tenant_id, key)
    return {
        "key": key,
        "value": resolved.value,
        "source": resolved.source,
        "overridden_at": resolved.overridden_at,
    }


@router.delete(
    "/{category}",
    response_model=ResolvedSettingResponse,
    status_code=status.HTTP_200_OK,
    summary="Clear one tenant-tier override; falls back to platform default.",
)
async def clear_tenant_integration(
    tenant_id: UUID,
    category: str,
    key: str = Query(...),
    context: RequestContext = Depends(requires_capability("tenant.manage_integrations")),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    cat = _validate_category(category)
    if key not in CATEGORY_KEYS[cat]:
        from app.core.errors import APIError

        raise APIError(
            status_code=400,
            title="Invalid key for category",
            detail=f"{key!r} does not belong to category {cat!r}",
            type_="https://agripulse.cloud/problems/integrations/invalid-key",
        )

    repo = SettingsRepository(public_session=public_session)
    deleted = await repo.delete_tenant_override(tenant_id=tenant_id, key=key)
    invalidate_defaults_cache()
    if deleted:
        audit = get_audit_service()
        await audit.record_archive(
            event_type="platform.tenant_integration_cleared",
            actor_user_id=context.user_id,
            subject_kind="tenant",
            subject_id=tenant_id,
            details={"key": key, "category": cat},
        )

    resolver = SettingsResolver(public_session=public_session)
    resolved = await resolver.get_tenant(tenant_id, key)
    return {
        "key": key,
        "value": resolved.value,
        "source": resolved.source,
        "overridden_at": resolved.overridden_at,
    }
