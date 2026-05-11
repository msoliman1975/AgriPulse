"""Read-only integration health service.

Queries the `v_farm_integration_health` / `v_block_integration_health`
views (created by tenant migration 0019 + extended in 0022) and the
`v_integration_recent_attempts` union view (added in 0022). All views
run in the tenant schema — the caller is expected to set search_path
before invocation, which is what `requires_capability` already arranges
via the auth middleware.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession


# Columns are listed explicitly so adding view columns can't accidentally
# break the API contract — we'd see the schema mismatch immediately.
_FARM_COLUMNS = (
    "farm_id, farm_name, "
    "weather_active_subs, weather_last_sync_at, weather_last_failed_at, "
    "imagery_active_subs, imagery_last_sync_at, imagery_failed_24h, "
    "weather_failed_24h, weather_running_count, imagery_running_count, "
    "weather_overdue_count, imagery_overdue_count"
)
_BLOCK_COLUMNS = (
    "block_id, farm_id, block_name, "
    "weather_active_subs, weather_last_sync_at, weather_last_failed_at, "
    "imagery_active_subs, imagery_last_sync_at, imagery_failed_24h, "
    "weather_failed_24h, weather_running_count, imagery_running_count, "
    "weather_overdue_count, imagery_overdue_count"
)
_ATTEMPT_COLUMNS = (
    "attempt_id, kind, subscription_id, block_id, farm_id, provider_code, "
    "started_at, completed_at, status, duration_ms, rows_ingested, "
    "error_code, error_message, scene_id"
)


class IntegrationsHealthService:
    def __init__(self, *, tenant_session: AsyncSession) -> None:
        self._tenant = tenant_session

    async def list_farms(self) -> list[dict[str, Any]]:
        rows = (
            await self._tenant.execute(
                text(
                    f"""
                    SELECT {_FARM_COLUMNS}
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
                    f"""
                    SELECT {_BLOCK_COLUMNS}
                    FROM v_block_integration_health
                    WHERE farm_id = :fid
                    ORDER BY block_name
                    """
                ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
                {"fid": farm_id},
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    # ---- Drill-down (PR-IH3) -----------------------------------------

    async def list_block_attempts(
        self,
        *,
        block_id: UUID,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Recent ingestion attempts for one block, newest first.

        `kind` filters 'weather'|'imagery'; None returns both interleaved.
        """
        clauses = ["block_id = :block_id"]
        params: dict[str, Any] = {"block_id": block_id, "limit": max(1, min(limit, 500))}
        if kind is not None:
            clauses.append("kind = :kind")
            params["kind"] = kind
        rows = (
            await self._tenant.execute(
                text(
                    f"""
                    SELECT {_ATTEMPT_COLUMNS}
                    FROM v_integration_recent_attempts
                    WHERE {' AND '.join(clauses)}
                    ORDER BY started_at DESC
                    LIMIT :limit
                    """
                ).bindparams(bindparam("block_id", type_=PG_UUID(as_uuid=True))),
                params,
            )
        ).mappings().all()
        return [dict(r) for r in rows]

    async def list_recent_attempts(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        farm_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Recent attempts across the tenant, newest first. Filterable."""
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        if kind is not None:
            clauses.append("kind = :kind")
            params["kind"] = kind
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if farm_id is not None:
            clauses.append("farm_id = :farm_id")
            params["farm_id"] = farm_id
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        stmt = text(
            f"""
            SELECT {_ATTEMPT_COLUMNS}
            FROM v_integration_recent_attempts
            {where}
            ORDER BY started_at DESC
            LIMIT :limit
            """
        )
        if farm_id is not None:
            stmt = stmt.bindparams(bindparam("farm_id", type_=PG_UUID(as_uuid=True)))
        rows = (await self._tenant.execute(stmt, params)).mappings().all()
        return [dict(r) for r in rows]


def get_integrations_health_service(
    tenant_session: AsyncSession,
) -> IntegrationsHealthService:
    return IntegrationsHealthService(tenant_session=tenant_session)
