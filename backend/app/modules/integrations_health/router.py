"""Integration health endpoints â€” read-only.

Mounted under /api/v1 by the app factory:

  GET /integrations/health/farms                       â€” Farm rollup
  GET /integrations/health/farms/{farm_id}/blocks      â€” per-Block detail
  GET /integrations/health/blocks/{block_id}/attempts  â€” per-Block run log (PR-IH3)
  GET /integrations/health/recent                      â€” tenant-wide recent runs (PR-IH3)
  GET /integrations/health/queue                       â€” overdue / running / stuck (PR-IH4)
  GET /integrations/health/queue/config                â€” the queue scan's thresholds

All gated on `tenant.read_integration_health`. PlatformSupport gets
this capability so support staff can diagnose tenant integration issues
without acting on them.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.integrations_health.providers_service import (
    ProviderHealthService,
)
from app.modules.integrations_health.schemas import (
    BlockIntegrationHealthResponse,
    FarmIntegrationHealthResponse,
    IntegrationAttemptRow,
    IntegrationHealthConfig,
    ProviderHealthRow,
    QueueEntry,
)
from app.modules.integrations_health.service import (
    IntegrationsHealthService,
    get_integrations_health_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["integrations-health"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> IntegrationsHealthService:
    return get_integrations_health_service(tenant_session=tenant_session)


def _providers_service(
    public_session: AsyncSession = Depends(get_db_session),
) -> ProviderHealthService:
    """Read-only provider liveness service.

    Uses the tenant session because the tenant-scoped query needs
    search_path set on the same connection that reads from public.
    PlatformAdmin routes mount their own dependency below.
    """
    return ProviderHealthService(public_session=public_session)


def _admin_providers_service(
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> ProviderHealthService:
    return ProviderHealthService(public_session=public_session)


def _ensure_tenant(context: RequestContext) -> None:
    if context.tenant_schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )


@router.get(
    "/integrations/health/farms",
    response_model=list[FarmIntegrationHealthResponse],
    summary="Per-Farm integration health rollup.",
)
async def list_farm_health(
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
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
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
    service: IntegrationsHealthService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_blocks(farm_id=farm_id)


@router.get(
    "/integrations/health/blocks/{block_id}/attempts",
    response_model=list[IntegrationAttemptRow],
    summary="Recent ingestion attempts for one Block (PR-IH3 drill-down).",
)
async def list_block_attempts(
    block_id: UUID,
    kind: Literal["weather", "imagery"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
    service: IntegrationsHealthService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_block_attempts(block_id=block_id, kind=kind, limit=limit)


@router.get(
    "/integrations/health/providers",
    response_model=list[ProviderHealthRow],
    summary="Provider liveness â€” tenant-scoped projection (PR-IH6).",
)
async def list_tenant_providers(
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
    service: ProviderHealthService = Depends(_providers_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    assert context.tenant_schema is not None  # asserted by _ensure_tenant
    return await service.list_tenant_providers(tenant_schema=context.tenant_schema)


@router.get(
    "/integrations/health/queue",
    response_model=list[QueueEntry],
    summary="Pipeline queue â€” overdue / running / stuck (PR-IH4).",
)
async def list_queue(
    kind: Literal["weather", "imagery"] | None = Query(default=None),
    state: Literal["overdue", "running", "stuck"] | None = Query(default=None),
    stuck_minutes: int | None = Query(default=None, ge=1, le=24 * 60),
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
    service: IntegrationsHealthService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    # The three thresholds come from settings, not from literals here and a
    # second set of literals in the service. `GET .../queue/config` returns
    # the same numbers, so the caption on the Queue tab cannot name a
    # threshold different from the one the scan used.
    settings = get_settings()
    return await service.list_queue(
        kind=kind,
        state=state,
        stuck_minutes=(
            stuck_minutes
            if stuck_minutes is not None
            else settings.integration_health_stuck_minutes
        ),
        default_weather_cadence_hours=settings.weather_default_cadence_hours,
        default_imagery_cadence_hours=settings.imagery_default_cadence_hours,
    )


@router.get(
    "/integrations/health/queue/config",
    response_model=IntegrationHealthConfig,
    summary="The thresholds the queue scan uses.",
)
async def read_queue_config(
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
) -> dict[str, Any]:
    _ensure_tenant(context)
    settings = get_settings()
    return {
        "stuck_minutes": settings.integration_health_stuck_minutes,
        "weather_default_cadence_hours": settings.weather_default_cadence_hours,
        "imagery_default_cadence_hours": settings.imagery_default_cadence_hours,
    }


@router.get(
    "/integrations/health/recent",
    response_model=list[IntegrationAttemptRow],
    summary="Tenant-wide recent ingestion attempts (PR-IH3 Runs tab).",
)
async def list_recent_attempts(
    kind: Literal["weather", "imagery"] | None = Query(default=None),
    status_filter: Literal["running", "succeeded", "failed", "skipped"] | None = Query(
        default=None, alias="status"
    ),
    farm_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability("tenant.read_integration_health")),
    service: IntegrationsHealthService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_recent_attempts(
        kind=kind, status=status_filter, farm_id=farm_id, limit=limit
    )
