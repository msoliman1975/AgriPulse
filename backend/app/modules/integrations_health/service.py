"""Read-only integration health service.

Queries the `v_farm_integration_health` / `v_block_integration_health`
views (created by tenant migration 0019). Both run in the tenant
schema — the caller is expected to set search_path before invocation,
which is what `requires_capability` already arranges via the auth
middleware.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession


class IntegrationsHealthService:
    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._tenant = tenant_session

    async def list_farms(self) -> list[dict[str, Any]]:
        rows = (
            await self._tenant.execute(
                text(
                    """
                    SELECT farm_id, farm_name,
                           weather_active_subs, weather_last_sync_at,
                           weather_last_failed_at,
                           imagery_active_subs, imagery_last_sync_at,
                           imagery_failed_24h
                    FROM v_farm_integration_health
                    ORDER BY farm_name
                    """
                )
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def list_blocks(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        rows = (
            await self._tenant.execute(
                text(
                    """
                    SELECT block_id, farm_id, block_name,
                           weather_active_subs, weather_last_sync_at,
                           weather_last_failed_at,
                           imagery_active_subs, imagery_last_sync_at,
                           imagery_failed_24h
                    FROM v_block_integration_health
                    WHERE farm_id = :fid
                    ORDER BY block_name
                    """
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]


def get_integrations_health_service(
    tenant_session: AsyncSession,
) -> IntegrationsHealthService:
    return IntegrationsHealthService(tenant_session=tenant_session)
