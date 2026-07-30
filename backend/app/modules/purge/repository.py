"""Data access for ``public.purge_jobs`` and ``public.purge_receipts``.

Raw SQL over the admin (public) session, matching ``backfill/repository.py``:
both tables are flat operational logs with jsonb payloads that the console reads
as rows, not objects. The column list is the only interpolated text — every
value is a bind parameter, so S608 is a false positive here.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

_JOB_COLS = """
    id, kind, target_id, target_label, tenant_id, tenant_schema, tenant_slug,
    status, phase, phases, preview, dry_run, reason, error,
    created_at, started_at, completed_at, created_by, created_by_email
"""

_RECEIPT_COLS = """
    id, job_id, kind, target_id, target_label, tenant_id, tenant_slug,
    actor_user_id, actor_email, reason, started_at, finished_at,
    deleted, verification, errors, created_at
"""

ACTIVE_STATUSES = ("queued", "running")


class PurgeConflictError(Exception):
    """A non-dry-run purge is already in flight for this target."""


class PurgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # -- jobs ----------------------------------------------------------------

    async def create_job(
        self,
        *,
        kind: str,
        target_id: UUID,
        target_label: str | None,
        tenant_id: UUID | None,
        tenant_schema: str | None,
        tenant_slug: str | None,
        preview: dict[str, Any],
        dry_run: bool,
        reason: str | None,
        created_by: UUID | None,
        created_by_email: str | None,
    ) -> dict[str, Any]:
        try:
            row = (
                await self._s.execute(
                    text(
                        f"""
                        INSERT INTO public.purge_jobs (
                            kind, target_id, target_label, tenant_id, tenant_schema,
                            tenant_slug, preview, dry_run, reason, created_by, created_by_email
                        ) VALUES (
                            :kind, :target_id, :target_label, :tenant_id, :tenant_schema,
                            :tenant_slug, CAST(:preview AS jsonb), :dry_run, :reason,
                            :created_by, :created_by_email
                        )
                        RETURNING {_JOB_COLS}
                        """
                    ),
                    {
                        "kind": kind,
                        "target_id": str(target_id),
                        "target_label": target_label,
                        # asyncpg needs explicit str() on nullable uuid binds.
                        "tenant_id": str(tenant_id) if tenant_id else None,
                        "tenant_schema": tenant_schema,
                        "tenant_slug": tenant_slug,
                        "preview": json.dumps(preview),
                        "dry_run": dry_run,
                        "reason": reason,
                        "created_by": str(created_by) if created_by else None,
                        "created_by_email": created_by_email,
                    },
                )
            ).mappings()
            await self._s.flush()
            return dict(row.one())
        except IntegrityError as exc:
            # uq_purge_jobs_active_target — one live purge per entity.
            raise PurgeConflictError(str(target_id)) from exc

    async def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(f"SELECT {_JOB_COLS} FROM public.purge_jobs WHERE id = :id"),  # noqa: S608
                {"id": str(job_id)},
            )
        ).mappings()
        found = row.one_or_none()
        return dict(found) if found else None

    async def list_jobs(
        self, *, tenant_id: UUID | None, status: str | None, limit: int
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = str(tenant_id)
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = (
            await self._s.execute(
                text(
                    f"SELECT {_JOB_COLS} FROM public.purge_jobs {where} "  # noqa: S608
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).mappings()
        return [dict(r) for r in rows]

    async def mark_running(self, job_id: UUID) -> None:
        await self._s.execute(
            text(
                "UPDATE public.purge_jobs SET status = 'running', started_at = now() "
                "WHERE id = :id AND started_at IS NULL"
            ),
            {"id": str(job_id)},
        )

    async def set_phase(self, job_id: UUID, phase: str, detail: dict[str, Any]) -> None:
        """Append a completed phase and point ``phase`` at it.

        Appending rather than replacing is what makes a crashed job resumable:
        the phases already recorded are the ones not to redo.
        """
        await self._s.execute(
            text(
                """
                UPDATE public.purge_jobs
                   SET phase = :phase,
                       phases = phases || CAST(:entry AS jsonb)
                 WHERE id = :id
                """
            ),
            {
                "id": str(job_id),
                "phase": phase,
                "entry": json.dumps([{"name": phase, "detail": detail}]),
            },
        )

    async def finish_job(self, job_id: UUID, *, status: str, error: str | None) -> None:
        await self._s.execute(
            text(
                "UPDATE public.purge_jobs SET status = :status, error = :error, "
                "completed_at = now() WHERE id = :id"
            ),
            {"id": str(job_id), "status": status, "error": error},
        )

    # -- receipts ------------------------------------------------------------

    async def create_receipt(
        self,
        *,
        job: dict[str, Any],
        actor_user_id: UUID | None,
        actor_email: str | None,
        deleted: dict[str, Any],
        verification: dict[str, Any],
        errors: list[str],
        job_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Write a tombstone.

        ``job_id`` is separate from ``job`` because whole-tenant purge has no
        job row — it runs inside the tenancy state machine — and the FK would
        reject a synthetic id. Pass None there; the receipt stands alone.
        """
        row = (
            await self._s.execute(
                text(
                    f"""
                    INSERT INTO public.purge_receipts (
                        job_id, kind, target_id, target_label, tenant_id, tenant_slug,
                        actor_user_id, actor_email, reason, started_at, finished_at,
                        deleted, verification, errors
                    ) VALUES (
                        :job_id, :kind, :target_id, :target_label, :tenant_id, :tenant_slug,
                        :actor_user_id, :actor_email, :reason, :started_at, now(),
                        CAST(:deleted AS jsonb), CAST(:verification AS jsonb),
                        CAST(:errors AS jsonb)
                    )
                    RETURNING {_RECEIPT_COLS}
                    """
                ),
                {
                    "job_id": str(job_id) if job_id else None,
                    "kind": job["kind"],
                    "target_id": str(job["target_id"]),
                    "target_label": job["target_label"],
                    "tenant_id": str(job["tenant_id"]) if job["tenant_id"] else None,
                    "tenant_slug": job["tenant_slug"],
                    "actor_user_id": str(actor_user_id) if actor_user_id else None,
                    "actor_email": actor_email,
                    "reason": job["reason"],
                    "started_at": job["started_at"],
                    "deleted": json.dumps(deleted, default=str),
                    "verification": json.dumps(verification, default=str),
                    "errors": json.dumps(errors),
                },
            )
        ).mappings()
        return dict(row.one())

    async def get_receipt_for_job(self, job_id: UUID) -> dict[str, Any] | None:
        row = (
            await self._s.execute(
                text(
                    f"SELECT {_RECEIPT_COLS} FROM public.purge_receipts "  # noqa: S608
                    "WHERE job_id = :id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": str(job_id)},
            )
        ).mappings()
        found = row.one_or_none()
        return dict(found) if found else None

    async def list_receipts(self, *, limit: int) -> list[dict[str, Any]]:
        rows = (
            await self._s.execute(
                text(
                    f"SELECT {_RECEIPT_COLS} FROM public.purge_receipts "  # noqa: S608
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).mappings()
        return [dict(r) for r in rows]
