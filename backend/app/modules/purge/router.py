"""Purge API — PlatformAdmin only.

Mounted at ``/api/v1/admin/purge``. Every endpoint is gated on
``platform.purge_data``, which is deliberately separate from
``platform.manage_tenants``: purge is the only irreversible delete in the
product, so it must be withholdable from someone who otherwise administers
tenants.

  GET  /preview                      — impact report, read-only
  POST /                             — submit (dry run or real)
  GET  /jobs                         — history
  GET  /jobs/{job_id}                — status + receipt
  GET  /receipts                     — tombstones, retained indefinitely
  GET  /tenants/{tenant_id}/entities — farm/block tree for the Data tab
  GET  /orphans                      — standalone residue scan

Whole-tenant purge is not here — it lives on
``POST /api/v1/admin/tenants/{id}/purge``, which owns the status machine and the
Keycloak teardown. It shares this module's manifest and writes the same receipts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.purge.repository import PurgeConflictError
from app.modules.purge.service import (
    ConfirmationMismatchError,
    NotArchivedError,
    PurgeService,
    TargetNotFoundError,
    get_purge_service,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.purge.scanner import scan_all, scan_stray_schemas
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1/admin/purge", tags=["admin-purge"])

_CAP = "platform.purge_data"

PurgeKind = Literal["block", "farm", "tenant_data"]


def _service(session: AsyncSession = Depends(get_admin_db_session)) -> PurgeService:
    return get_purge_service(session)


# --- schemas ---------------------------------------------------------------


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PurgeKind
    id: UUID
    tenant_id: UUID
    # Must equal the entity's own name/code (or the tenant slug). Typing it is
    # the last gate before an irreversible action.
    confirmation: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=500)
    # A rehearsal: runs the full manifest inside a transaction and rolls back,
    # so the reported counts are measured rather than estimated.
    dry_run: bool = False


class JobRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    target_id: UUID
    target_label: str | None
    tenant_id: UUID | None
    tenant_slug: str | None
    status: str
    phase: str | None
    phases: list[dict[str, Any]]
    preview: dict[str, Any]
    dry_run: bool
    reason: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    created_by_email: str | None
    receipt: dict[str, Any] | None = None


# --- endpoints -------------------------------------------------------------


@router.get("/preview")
async def preview(
    kind: PurgeKind,
    id: UUID,
    tenant_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: PurgeService = Depends(_service),
) -> dict[str, Any]:
    del context
    try:
        return await service.preview(kind=kind, target_id=id, tenant_id=tenant_id)
    except TargetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def submit(
    body: PurgeRequest,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: PurgeService = Depends(_service),
) -> dict[str, Any]:
    try:
        return await service.submit(
            kind=body.kind,
            target_id=body.id,
            tenant_id=body.tenant_id,
            confirmation=body.confirmation,
            reason=body.reason,
            dry_run=body.dry_run,
            actor_id=getattr(context, "user_id", None),
            actor_email=getattr(context, "email", None),
        )
    except TargetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NotArchivedError as exc:
        # 409, not 400: the request is well-formed, the entity is in the wrong
        # state. Archiving it makes the same request succeed.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ConfirmationMismatchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except PurgeConflictError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a purge is already in progress for this target"
        ) from exc


@router.get("/jobs", response_model=list[JobRow])
async def list_jobs(
    tenant_id: UUID | None = None,
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: PurgeService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_jobs(tenant_id=tenant_id, status=job_status, limit=limit)


@router.get("/jobs/{job_id}", response_model=JobRow)
async def get_job(
    job_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: PurgeService = Depends(_service),
) -> dict[str, Any]:
    del context
    job = await service.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "purge job not found")
    return job


@router.get("/receipts")
async def list_receipts(
    limit: int = Query(default=50, ge=1, le=200),
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: PurgeService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_receipts(limit=limit)


@router.get("/tenants/{tenant_id}/entities")
async def list_entities(
    tenant_id: UUID,
    context: RequestContext = Depends(requires_capability(_CAP)),
    service: PurgeService = Depends(_service),
) -> dict[str, Any]:
    del context
    try:
        return await service.list_tenant_entities(tenant_id)
    except TargetNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/orphans")
async def orphans(
    context: RequestContext = Depends(requires_capability(_CAP)),
    session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    """Standalone residue sweep across public + every live tenant schema.

    Reports what earlier purges left behind — the pre-existing orphans this
    module was built to stop creating.
    """
    del context
    result = (await scan_all(session)).as_dict()
    result["stray_schemas"] = await scan_stray_schemas(session)
    return result
