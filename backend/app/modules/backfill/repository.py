"""Data access for ``public.backfill_runs``.

Raw SQL over the admin (public) session. There is no ORM model here on
purpose: the table is a flat operational log with two jsonb blobs, and the
console reads it as rows rather than as objects.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Columns the console renders. Kept in one place so list and detail agree.
# This constant and the closed-set WHERE clauses below are the only things
# interpolated into these queries -- every value is a bind parameter -- so
# the S608 "possible SQL injection" heuristic is a false positive here.
_COLS = """
    id, tenant_id, tenant_schema, tenant_name, farm_id, farm_name,
    kind, sources, window_from, window_to, status, error, progress,
    created_at, started_at, completed_at, created_by, created_by_email
"""

# Runs that still count as occupying a farm.
ACTIVE_STATUSES = ("queued", "running")


class BackfillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        tenant_schema: str,
        tenant_name: str | None,
        farm_id: UUID,
        farm_name: str | None,
        kind: str,
        sources: dict[str, bool],
        window_from: str,
        window_to: str,
        created_by: UUID | None,
        created_by_email: str | None,
    ) -> dict[str, Any]:
        row = (
            await self._s.execute(
                text(
                    f"""
                    INSERT INTO public.backfill_runs (
                        tenant_id, tenant_schema, tenant_name, farm_id, farm_name,
                        kind, sources, window_from, window_to, created_by, created_by_email
                    ) VALUES (
                        :tenant_id, :tenant_schema, :tenant_name, :farm_id, :farm_name,
                        :kind, CAST(:sources AS jsonb), CAST(:window_from AS date),
                        CAST(:window_to AS date), :created_by, :created_by_email
                    )
                    RETURNING {_COLS}
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "tenant_schema": tenant_schema,
                    "tenant_name": tenant_name,
                    "farm_id": str(farm_id),
                    "farm_name": farm_name,
                    "kind": kind,
                    "sources": json.dumps(sources),
                    "window_from": window_from,
                    "window_to": window_to,
                    # asyncpg needs an explicit cast on nullable uuid binds.
                    "created_by": str(created_by) if created_by else None,
                    "created_by_email": created_by_email,
                },
            )
        ).mappings()
        return dict(row.one())

    async def list_runs(
        self,
        *,
        tenant_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where = []
        params: dict[str, Any] = {"limit": limit}
        if tenant_id is not None:
            where.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)
        if status:
            where.append("status = :status")
            params["status"] = status
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT {_COLS}
              FROM public.backfill_runs
              {clause}
             ORDER BY created_at DESC
             LIMIT :limit
        """  # noqa: S608 - only _COLS and the closed-set clause interpolate
        rows = (await self._s.execute(text(sql), params)).mappings()
        return [dict(r) for r in rows]

    async def get(self, run_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(f"SELECT {_COLS} FROM public.backfill_runs WHERE id = :rid"),  # noqa: S608
                {"rid": str(run_id)},
            )
        ).mappings()
        found = row.one_or_none()
        return dict(found) if found else None

    async def active_for_farm(self, farm_id: UUID) -> dict[str, Any] | None:
        """The run currently occupying this farm, if any.

        Used to return a clean 409 before hitting the partial unique index
        that enforces the same rule at the database level.
        """
        sql = f"""
            SELECT {_COLS}
              FROM public.backfill_runs
             WHERE farm_id = :fid
               AND status IN ('queued', 'running')
             LIMIT 1
        """  # noqa: S608 - only _COLS interpolates
        row = (await self._s.execute(text(sql), {"fid": str(farm_id)})).mappings()
        found = row.one_or_none()
        return dict(found) if found else None

    async def fail(self, run_id: UUID, error: str) -> None:
        await self._s.execute(
            text(
                """
                UPDATE public.backfill_runs
                   SET status = 'failed', error = :err, completed_at = now()
                 WHERE id = :rid
                """
            ),
            {"rid": str(run_id), "err": error[:2000]},
        )
