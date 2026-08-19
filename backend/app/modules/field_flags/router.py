"""Field-flag routes.

Mounted under /api/v1 by the app factory:

  GET  /farms/{farm_id}/field-flags      — the map layer and the panel
  POST /farms/{farm_id}/field-flags      — a scout raises one
  GET  /field-flags/{id}                 — one flag with its thread
  POST /field-flags/{id}/comments        — reply
  POST /field-flags/{id}:close           — reason + comment, both required
  POST /field-flags/{id}:reopen          — comment required, resets the pin
  POST /field-flags:upload-init          — presigned PUT for one photo

RBAC uses capabilities that already exist, so this module adds none:

  * **raise / upload** -> ``scouting.record``. It has been declared since the
    beginning with ``status: stub`` and implemented by zero endpoints; this is
    the module it was reserved for.
  * **comment / close / reopen** -> ``scouting.dispatch``, already the "can
    send somebody to look at this" capability, which is the same population
    that should be answering a flag.
  * **read** -> ``scouting.visit.read``, held by every role that can see the
    farm's work at all.

One deliberate widening: the scout who raised a flag may comment on it and
reopen it without holding ``scouting.dispatch``. A thread the reporter cannot
answer is not a conversation, and being told your flag was closed with no way
to say "it is still there" is worse than not being told.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.field_flags.schemas import (
    FieldFlagResponse,
    FlagAttachmentInitRequest,
    FlagAttachmentInitResponse,
    FlagCloseRequest,
    FlagCommentRequest,
    FlagCreateRequest,
    FlagReopenRequest,
)
from app.modules.field_flags.service import FieldFlagService, get_field_flag_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["field-flags"])


def _service(
    context: RequestContext = Depends(get_current_context),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> FieldFlagService:
    return get_field_flag_service(
        tenant_session=tenant_session, tenant_schema=context.tenant_schema
    )


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


def _ensure_user(context: RequestContext) -> UUID:
    if context.user_id is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="User context required",
            detail="This endpoint requires a user-scoped token.",
            type_="https://agripulse.cloud/problems/user-required",
        )
    return context.user_id


async def _may_answer(
    *, context: RequestContext, service: FieldFlagService, flag_id: UUID
) -> dict[str, Any]:
    """Dispatchers may answer any flag; the reporter may answer their own."""
    flag = await service.get_flag(flag_id=flag_id, with_thread=False)
    if has_capability(context, "scouting.dispatch", farm_id=flag["farm_id"]):
        return flag
    if context.user_id is not None and flag["raised_by"] == context.user_id:
        return flag
    # 404 rather than 403: a caller who cannot act on this flag should not
    # learn it exists, which is how the rest of this codebase answers too.
    raise APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Field flag not found",
        detail=f"No field flag with id {flag_id}.",
        type_="https://agripulse.cloud/problems/field-flags/not-found",
        extras={"flag_id": str(flag_id)},
    )


@router.get(
    "/farms/{farm_id}/field-flags",
    response_model=list[FieldFlagResponse],
    summary="Field flags on a farm — the map layer and the panel.",
)
async def list_flags(
    farm_id: UUID,
    open_only: Annotated[bool, Query(description="Only flags still open.")] = False,
    pinned_only: Annotated[
        bool,
        Query(
            description=(
                "Only flags whose pin lifetime has not run out. This is what the map "
                "layer asks for; the panel asks without it, because an unpinned flag "
                "is still open work."
            )
        ),
    ] = False,
    context: RequestContext = Depends(
        requires_capability("scouting.visit.read", farm_id_param="farm_id")
    ),
    service: FieldFlagService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_flags(farm_id=farm_id, open_only=open_only, pinned_only=pinned_only)


@router.post(
    "/farms/{farm_id}/field-flags",
    response_model=FieldFlagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a flag — something nobody asked about.",
)
async def raise_flag(
    farm_id: UUID,
    payload: FlagCreateRequest,
    context: RequestContext = Depends(
        requires_capability("scouting.record", farm_id_param="farm_id")
    ),
    service: FieldFlagService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    return await service.raise_flag(
        farm_id=farm_id, payload=payload, actor_user_id=_ensure_user(context)
    )


@router.post(
    "/field-flags:upload-init",
    response_model=FlagAttachmentInitResponse,
    summary="Begin a field-flag photo upload (presigned PUT).",
)
async def init_photo_upload(
    payload: FlagAttachmentInitRequest,
    context: RequestContext = Depends(get_current_context),
    service: FieldFlagService = Depends(_service),
    admin_session: AsyncSession = Depends(get_admin_db_session),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    if not has_capability(context, "scouting.record", farm_id=payload.farm_id):
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail="Recording a field flag requires scouting.record on this farm.",
            type_="https://agripulse.cloud/problems/forbidden",
        )
    from sqlalchemy import text

    row = (
        await admin_session.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :s"), {"s": schema}
        )
    ).first()
    if row is None:
        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant unresolvable",
            detail="This token's tenant has no record.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return await service.init_photo_upload(
        farm_id=payload.farm_id,
        tenant_id=row.id,
        content_type=payload.content_type,
        content_length=payload.content_length,
        filename=payload.filename,
    )


@router.get(
    "/field-flags/{flag_id}",
    response_model=FieldFlagResponse,
    summary="One flag, with its photos and its thread.",
)
async def get_flag(
    flag_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: FieldFlagService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    flag = await service.get_flag(flag_id=flag_id)
    # The farm is on the row, so the gate is checked after the fetch — the
    # same pattern plans and imagery use for their id-addressed reads.
    if not has_capability(context, "scouting.visit.read", farm_id=flag["farm_id"]):
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Field flag not found",
            detail=f"No field flag with id {flag_id}.",
            type_="https://agripulse.cloud/problems/field-flags/not-found",
        )
    return flag


@router.post(
    "/field-flags/{flag_id}/comments",
    response_model=FieldFlagResponse,
    summary="Reply on a flag's thread.",
)
async def comment(
    flag_id: UUID,
    payload: FlagCommentRequest,
    context: RequestContext = Depends(get_current_context),
    service: FieldFlagService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    await _may_answer(context=context, service=service, flag_id=flag_id)
    return await service.comment(
        flag_id=flag_id, body=payload.body, actor_user_id=_ensure_user(context)
    )


@router.post(
    "/field-flags/{flag_id}:close",
    response_model=FieldFlagResponse,
    summary="Close a flag. A reason and a comment are both required.",
)
async def close_flag(
    flag_id: UUID,
    payload: FlagCloseRequest,
    context: RequestContext = Depends(get_current_context),
    service: FieldFlagService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    flag = await service.get_flag(flag_id=flag_id, with_thread=False)
    # Closing is a supervisor's act, not the reporter's: a scout closing their
    # own flag would be answering their own question.
    if not has_capability(context, "scouting.dispatch", farm_id=flag["farm_id"]):
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Field flag not found",
            detail=f"No field flag with id {flag_id}.",
            type_="https://agripulse.cloud/problems/field-flags/not-found",
        )
    return await service.close(
        flag_id=flag_id,
        reason=payload.reason,
        comment=payload.comment,
        actor_user_id=_ensure_user(context),
    )


@router.post(
    "/field-flags/{flag_id}:reopen",
    response_model=FieldFlagResponse,
    summary="Re-open a closed flag. Requires a comment; restarts the pin.",
)
async def reopen_flag(
    flag_id: UUID,
    payload: FlagReopenRequest,
    context: RequestContext = Depends(get_current_context),
    service: FieldFlagService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    await _may_answer(context=context, service=service, flag_id=flag_id)
    return await service.reopen(
        flag_id=flag_id, comment=payload.comment, actor_user_id=_ensure_user(context)
    )
