"""Integration health endpoints — read-only.

Mounted under /api/v1 by the app factory:

  GET /integrations/health/farms                       — Farm rollup
  GET /integrations/health/farms/{farm_id}/blocks      — per-Block detail

Both gated on `tenant.read_integration_health`. PlatformSupport gets
this capability so support staff can diagnose tenant integration issues
without acting on them.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations_health.schemas import (
    BlockIntegrationHealthResponse,
    FarmIntegrationHealthResponse,
)
from app.modules.integrations_health.service import (
    IntegrationsHealthService,
    get_integrations_health_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["integrations-health"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> IntegrationsHealthService:
    return get_integrations_health_service(tenant_session=tenant_session)


def _ensure_tenant(context: RequestContext) -> None:
    if context.tenant_schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://missionagre.io/problems/tenant-required",
        )


@router.get(
    "/integrations/health/farms",
    response_model=list[FarmIntegrationHealthResponse],
    summary="Per-Farm integration health rollup.",
)
async def list_farm_health(
    context: RequestContext = Depends(
        requires_capability("tenant.read_integration_health")
    ),
    service: IntegrationsHealthService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_farms()


@router.get(
    "/integrations/health/farms/{farm_id}/blocks",
    response_model=list[BlockIntegrationHealthResponse],
    summary="Per-Block integration health for one Farm.",
)
async def list_block_health(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("tenant.read_integration_health")
    ),
    service: IntegrationsHealthService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_blocks(farm_id=farm_id)
