"""Cross-tenant integration health rollup for the Platform portal.

Aggregates `v_farm_integration_health` (per-tenant view created in
PR-Set2) across every active tenant. Returns one row per tenant
with summary counts so /platform/integrations/health can show
"which tenant has stale weather?" at a glance.

Implementation: for each tenant, switch search_path, hit the view,
sum / max into a tenant-level row. Linear cost in tenant count;
acceptable while we have tens of tenants. If this gets slow, the
likely fix is a refreshed materialized view in `public` rather than
on-demand aggregation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from uuid import UUID

from app.core.logging import get_logger
from app.modules.integrations_health.providers_service import ProviderHealthService
from app.modules.integrations_health.schemas import (
    ProviderHealthRow,
    ProviderProbeRow,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session, sanitize_tenant_schema
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/integrations", tags=["admin-integrations-health"])


class TenantHealthRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    farms_count: int
    weather_active_subs: int
    weather_last_sync_at: datetime | None
    weather_failed_24h: int
    imagery_active_subs: int
    imagery_last_sync_at: datetime | None
    imagery_failed_24h: int


@router.get("/health", response_model=list[TenantHealthRow])
async def cross_tenant_health(
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    del context
    log = get_logger(__name__)

    tenants = (
        await public_session.execute(
            text(
                """
                SELECT id, slug, name, schema_name
                FROM public.tenants
                WHERE status = 'active' AND deleted_at IS NULL
                ORDER BY slug
                """
            )
        )
    ).all()

    out: list[dict[str, Any]] = []
    for t in tenants:
        try:
            schema = sanitize_tenant_schema(t.schema_name)
        except ValueError:
            log.warning("cross_tenant_health_invalid_schema", schema=t.schema_name)
            continue

        # Switch into the tenant schema and aggregate the view.
        await public_session.execute(
            text(f"SET LOCAL search_path TO {schema}, public")
        )
        try:
            row = (
                await public_session.execute(
                    text(
                        """
                        SELECT COUNT(*) AS farms_count,
                               COALESCE(SUM(weather_active_subs), 0) AS w_subs,
                               MAX(weather_last_sync_at) AS w_last,
                               COALESCE(SUM(
                                   CASE WHEN weather_last_failed_at IS NOT NULL
                                        AND weather_last_failed_at >
                                            now() - interval '24 hours'
                                        THEN 1 ELSE 0 END
                               ), 0) AS w_failed_24h,
                               COALESCE(SUM(imagery_active_subs), 0) AS i_subs,
                               MAX(imagery_last_sync_at) AS i_last,
                               COALESCE(SUM(imagery_failed_24h), 0) AS i_failed_24h
                        FROM v_farm_integration_health
                        """
                    )
                )
            ).first()
        except Exception as exc:  # noqa: BLE001
            # Tenant schema might be mid-migration / missing the view.
            log.warning(
                "cross_tenant_health_query_failed",
                schema=schema,
                error=str(exc),
            )
            continue
        finally:
            # Reset search_path so the next iteration can re-set safely.
            await public_session.execute(text("SET LOCAL search_path TO public"))

        out.append(
            {
                "tenant_id": t.id,
                "tenant_slug": t.slug,
                "tenant_name": t.name,
                "farms_count": int(row.farms_count or 0),
                "weather_active_subs": int(row.w_subs or 0),
                "weather_last_sync_at": row.w_last,
                "weather_failed_24h": int(row.w_failed_24h or 0),
                "imagery_active_subs": int(row.i_subs or 0),
                "imagery_last_sync_at": row.i_last,
                "imagery_failed_24h": int(row.i_failed_24h or 0),
            }
        )
    # Silence unused-import warnings on PG_UUID + bindparam (kept for
    # potential future expansion — e.g. filter by category).
    _ = bindparam("x", type_=PG_UUID(as_uuid=True))
    return out


# ---- Provider probes (PR-IH6) -------------------------------------------


@router.get("/health/providers", response_model=list[ProviderHealthRow])
async def list_platform_providers(
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    """Every active provider catalog row + its latest probe."""
    del context
    service = ProviderHealthService(public_session=public_session)
    return await service.list_platform_providers()


@router.get("/health/probes", response_model=list[ProviderProbeRow])
async def list_recent_probes(
    provider_kind: str,
    provider_code: str,
    limit: int = 200,
    context: RequestContext = Depends(
        requires_capability("platform.manage_tenants")
    ),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> list[dict[str, Any]]:
    """Probe history for one provider — drill-down from the Providers tab."""
    del context
    service = ProviderHealthService(public_session=public_session)
    return await service.list_recent_probes(
        provider_kind=provider_kind, provider_code=provider_code, limit=limit
    )
