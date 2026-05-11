"""Platform tenant drill-in (PR-IH7).

Mirrors every `/api/v1/integrations/health/*` route under
`/api/v1/admin/tenants/{tenant_id}/integrations/health/*` so the
Platform portal can show the same Overview / Runs / Queue / Providers
tabs scoped to a specific tenant — without the PlatformAdmin needing
to switch JWTs.

All routes gated on `platform.manage_tenants`. Internally each route:

  1. Resolves `tenant_id → schema_name` from `public.tenants`
  2. Sets `search_path` on the admin session to that tenant's schema
  3. Calls the same `IntegrationsHealthService` methods the tenant
     portal uses.

The mirror shape (basePath replacement) keeps the React API client
mostly identical — see `IntegrationsHealthPage.basePath` prop.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.integrations_health.providers_service import ProviderHealthService
from app.modules.integrations_health.schemas import (
    BlockIntegrationHealthResponse,
    FarmIntegrationHealthResponse,
    IntegrationAttemptRow,
    ProviderHealthRow,
    QueueEntry,
)
from app.modules.integrations_health.service import (
    IntegrationsHealthService,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, sanitize_tenant_schema
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["admin-tenant-health-drill"])


async def _resolve_and_scope(
    tenant_id: UUID,
    session: AsyncSession,
) -> str:
    """Look up `tenants.schema_name` for tenant_id, set search_path, return schema."""
    row = (
        await session.execute(
            text(
                """
                SELECT schema_name
                FROM public.tenants
                WHERE id = :id
                  AND status = 'active'
                  AND deleted_at IS NULL
                """
            ),
            {"id": tenant_id},
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found or not active.",
        )
    schema = sanitize_tenant_schema(row.schema_name)
    await session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
    return schema


@router.get(
    "/{tenant_id}/integrations/health/farms",
    response_model=list[FarmIntegrationHealthResponse],
)
async def drill_farms(
    tenant_id: UUID,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    await _resolve_and_scope(tenant_id, session)
    service = IntegrationsHealthService(tenant_session=session)
    return await service.list_farms()


@router.get(
    "/{tenant_id}/integrations/health/farms/{farm_id}/blocks",
    response_model=list[BlockIntegrationHealthResponse],
)
async def drill_blocks(
    tenant_id: UUID,
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    await _resolve_and_scope(tenant_id, session)
    service = IntegrationsHealthService(tenant_session=session)
    return await service.list_blocks(farm_id=farm_id)


@router.get(
    "/{tenant_id}/integrations/health/blocks/{block_id}/attempts",
    response_model=list[IntegrationAttemptRow],
)
async def drill_block_attempts(
    tenant_id: UUID,
    block_id: UUID,
    kind: Literal["weather", "imagery"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    await _resolve_and_scope(tenant_id, session)
    service = IntegrationsHealthService(tenant_session=session)
    return await service.list_block_attempts(block_id=block_id, kind=kind, limit=limit)


@router.get(
    "/{tenant_id}/integrations/health/recent",
    response_model=list[IntegrationAttemptRow],
)
async def drill_recent(
    tenant_id: UUID,
    kind: Literal["weather", "imagery"] | None = Query(default=None),
    status_filter: Literal["running", "succeeded", "failed", "skipped"] | None = Query(
        default=None, alias="status"
    ),
    farm_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    await _resolve_and_scope(tenant_id, session)
    service = IntegrationsHealthService(tenant_session=session)
    return await service.list_recent_attempts(
        kind=kind, status=status_filter, farm_id=farm_id, limit=limit
    )


@router.get(
    "/{tenant_id}/integrations/health/queue",
    response_model=list[QueueEntry],
)
async def drill_queue(
    tenant_id: UUID,
    kind: Literal["weather", "imagery"] | None = Query(default=None),
    state: Literal["overdue", "running", "stuck"] | None = Query(default=None),
    stuck_minutes: int = Query(default=30, ge=1, le=24 * 60),
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    await _resolve_and_scope(tenant_id, session)
    service = IntegrationsHealthService(tenant_session=session)
    return await service.list_queue(kind=kind, state=state, stuck_minutes=stuck_minutes)


@router.get(
    "/{tenant_id}/integrations/health/providers",
    response_model=list[ProviderHealthRow],
)
async def drill_providers(
    tenant_id: UUID,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    """Tenant-scoped provider list (only providers this tenant subscribes to)."""
    del context
    schema = await _resolve_and_scope(tenant_id, session)
    service = ProviderHealthService(public_session=session)
    return await service.list_tenant_providers(tenant_schema=schema)
