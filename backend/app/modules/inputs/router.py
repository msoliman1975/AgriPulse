"""Inputs catalogue routes (decision D20).

  GET   /api/v1/inputs                 platform rows + the caller's tenant rows
  GET   /api/v1/inputs/{id}
  POST  /api/v1/inputs                 create: a platform caller writes platform
                                       rows (platform.manage_crops); a tenant
                                       caller writes its own (tenant.manage_settings)
  PATCH /api/v1/inputs/{id}            edit or retire a row the caller owns
  PUT   /api/v1/inputs/{id}/doses      replace the recommended doses

Neither scope can edit the other's rows. There is no delete: a wrong input
is retired, so a plan that used it still says what it used. Writes are
audited.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.audit import get_audit_service
from app.modules.inputs.repository import InputsRepository
from app.modules.inputs.schemas import (
    Category,
    InputCreateRequest,
    InputDosesRequest,
    InputResponse,
    InputUpdateRequest,
)
from app.shared.arabic_required import merged, require_arabic
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import has_capability

router = APIRouter(prefix="/api/v1/inputs", tags=["inputs"])


def _repo(session: AsyncSession = Depends(get_admin_db_session)) -> InputsRepository:
    return InputsRepository(session)


def _problem(code: int, title: str, detail: str, slug: str) -> APIError:
    return APIError(
        status_code=code,
        title=title,
        detail=detail,
        type_=f"https://agripulse.cloud/problems/{slug}",
    )


# D26: a platform input carries an Arabic name beside the English one. A
# tenant's own inputs may stay English only.
_NAME_PAIRS = (("name_en", "name_ar"),)


def _ensure_can_write(context: RequestContext) -> None:
    """A platform caller curates the platform catalogue; a tenant its own rows."""
    capability = "platform.manage_crops" if context.tenant_id is None else "tenant.manage_settings"
    if not has_capability(context, capability):
        raise _problem(403, "Not allowed", f"Writing inputs needs {capability}.", "forbidden")


async def _owned(repo: InputsRepository, input_id: UUID, context: RequestContext) -> dict[str, Any]:
    row = await repo.get_input(input_id)
    if row is None or (row["tenant_id"] is not None and row["tenant_id"] != context.tenant_id):
        raise _problem(404, "Input not found", f"No input {input_id}.", "input-not-found")
    if row["tenant_id"] != context.tenant_id:
        raise _problem(
            403,
            "Not your input",
            "Platform inputs are edited by the platform; a tenant edits only its own.",
            "input-not-owned",
        )
    return row


@router.get("", response_model=list[InputResponse])
async def list_inputs(
    crop_path: str | None = Query(default=None, max_length=255),
    category: Category | None = None,
    q: str | None = Query(default=None, max_length=200),
    include_inactive: bool = False,
    context: RequestContext = Depends(get_current_context),
    repo: InputsRepository = Depends(_repo),
) -> list[dict[str, Any]]:
    return await repo.list_inputs(
        tenant_id=context.tenant_id,
        crop_path=crop_path,
        category=category,
        q=q,
        include_inactive=include_inactive,
    )


@router.get("/{input_id}", response_model=InputResponse)
async def get_input(
    input_id: UUID,
    context: RequestContext = Depends(get_current_context),
    repo: InputsRepository = Depends(_repo),
) -> dict[str, Any]:
    row = await repo.get_input(input_id)
    if row is None or (row["tenant_id"] is not None and row["tenant_id"] != context.tenant_id):
        raise _problem(404, "Input not found", f"No input {input_id}.", "input-not-found")
    return row


@router.post("", response_model=InputResponse, status_code=status.HTTP_201_CREATED)
async def create_input(
    payload: InputCreateRequest,
    context: RequestContext = Depends(get_current_context),
    repo: InputsRepository = Depends(_repo),
) -> dict[str, Any]:
    _ensure_can_write(context)
    if context.tenant_id is None:
        require_arabic(payload.model_dump(), _NAME_PAIRS)
    if await repo.code_taken(payload.code, context.tenant_id):
        raise _problem(
            409,
            "Code already used",
            f"An input with code {payload.code} exists.",
            "input-code-taken",
        )
    fields = payload.model_dump(exclude_none=True)
    input_id = await repo.create(context.tenant_id, fields, context.user_id)
    await get_audit_service().record_archive(
        event_type="catalog.input_created",
        actor_user_id=context.user_id,
        subject_kind="input",
        subject_id=input_id,
        details={
            "code": payload.code,
            "tenant_id": str(context.tenant_id) if context.tenant_id else None,
        },
    )
    row = await repo.get_input(input_id)
    assert row is not None
    return row


@router.patch("/{input_id}", response_model=InputResponse)
async def update_input(
    input_id: UUID,
    payload: InputUpdateRequest,
    context: RequestContext = Depends(get_current_context),
    repo: InputsRepository = Depends(_repo),
) -> dict[str, Any]:
    _ensure_can_write(context)
    existing = await _owned(repo, input_id, context)
    fields = payload.model_dump(exclude_unset=True)
    if existing["tenant_id"] is None:
        require_arabic(merged(existing, fields), _NAME_PAIRS, before=existing)
    await repo.update(input_id, fields, context.user_id)
    await get_audit_service().record_archive(
        event_type="catalog.input_updated",
        actor_user_id=context.user_id,
        subject_kind="input",
        subject_id=input_id,
        details={"fields": sorted(fields)},
    )
    row = await repo.get_input(input_id)
    assert row is not None
    return row


@router.put("/{input_id}/doses", response_model=InputResponse)
async def replace_doses(
    input_id: UUID,
    payload: InputDosesRequest,
    context: RequestContext = Depends(get_current_context),
    repo: InputsRepository = Depends(_repo),
) -> dict[str, Any]:
    _ensure_can_write(context)
    await _owned(repo, input_id, context)
    await repo.replace_doses(input_id, [d.model_dump() for d in payload.doses])
    await get_audit_service().record_archive(
        event_type="catalog.input_doses_replaced",
        actor_user_id=context.user_id,
        subject_kind="input",
        subject_id=input_id,
        details={"doses": len(payload.doses)},
    )
    row = await repo.get_input(input_id)
    assert row is not None
    return row
