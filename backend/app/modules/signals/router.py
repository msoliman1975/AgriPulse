"""FastAPI routes for the signals module.

Mounted under /api/v1 by the app factory.

  GET    /signals/definitions
  POST   /signals/definitions
  GET    /signals/definitions/{id}
  PATCH  /signals/definitions/{id}
  DELETE /signals/definitions/{id}
  GET    /signals/definitions/{id}/assignments
  POST   /signals/definitions/{id}/assignments
  DELETE /signals/assignments/{assignment_id}
  POST   /signals/observations:upload-init
  POST   /signals/definitions/{id}/observations
  GET    /signals/observations

RBAC follows data_model Â§ 9 + capabilities.yaml:
  * `signal.read` for definition / observation reads.
  * `signal.define` for definition / assignment writes (tenant-scoped).
  * `signal.record` for recording observations (farm-scoped).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.signals.schemas import (
    SignalAssignmentCreateRequest,
    SignalAssignmentResponse,
    SignalAttachmentInitRequest,
    SignalAttachmentInitResponse,
    SignalDefinitionCreateRequest,
    SignalDefinitionResponse,
    SignalDefinitionUpdateRequest,
    SignalObservationCreateRequest,
    SignalObservationResponse,
)
from app.modules.signals.service import SignalsServiceImpl, get_signals_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(prefix="/api/v1", tags=["signals"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
) -> SignalsServiceImpl:
    return get_signals_service(tenant_session=tenant_session)


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://agripulse.cloud/problems/tenant-required",
        )
    return schema


async def _resolve_tenant_id(*, schema: str, tenant_session: AsyncSession) -> UUID:
    """Round-trip the tenant id from the public catalog. The S3 key
    layout uses tenant_id as the partition prefix."""
    row = (
        await tenant_session.execute(
            text("SELECT id FROM public.tenants WHERE schema_name = :s"),
            {"s": schema},
        )
    ).first()
    if row is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Tenant not found",
            detail="Could not resolve tenant id from JWT-claimed schema.",
            type_="https://agripulse.cloud/problems/tenant-not-found",
        )
    return row.id


# ---------- Definitions ---------------------------------------------------


@router.get(
    "/signals/definitions",
    response_model=list[SignalDefinitionResponse],
    summary="List signal definitions in the current tenant.",
)
async def list_definitions(
    include_inactive: bool = Query(default=False),
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(await service.list_definitions(include_inactive=include_inactive))


@router.post(
    "/signals/definitions",
    response_model=SignalDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a signal definition (tenant admins).",
)
async def create_definition(
    payload: SignalDefinitionCreateRequest,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.create_definition(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        value_kind=payload.value_kind,
        unit=payload.unit,
        categorical_values=payload.categorical_values,
        value_min=payload.value_min,
        value_max=payload.value_max,
        attachment_allowed=payload.attachment_allowed,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.get(
    "/signals/definitions/{definition_id}",
    response_model=SignalDefinitionResponse,
    summary="Read a signal definition.",
)
async def get_definition(
    definition_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    return await service.get_definition(definition_id=definition_id)


@router.patch(
    "/signals/definitions/{definition_id}",
    response_model=SignalDefinitionResponse,
    summary="Update a signal definition.",
)
async def update_definition(
    definition_id: UUID,
    payload: SignalDefinitionUpdateRequest,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    updates = payload.model_dump(exclude_unset=True)
    return await service.update_definition(
        definition_id=definition_id,
        updates=updates,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.delete(
    "/signals/definitions/{definition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Soft-delete a signal definition.",
)
async def delete_definition(
    definition_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    await service.delete_definition(
        definition_id=definition_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---------- Assignments ---------------------------------------------------


@router.get(
    "/signals/definitions/{definition_id}/assignments",
    response_model=list[SignalAssignmentResponse],
    summary="List assignments for a signal definition.",
)
async def list_assignments(
    definition_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(await service.list_assignments(definition_id=definition_id))


@router.post(
    "/signals/definitions/{definition_id}/assignments",
    response_model=SignalAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a signal definition to a farm/block (or tenant-wide).",
)
async def create_assignment(
    definition_id: UUID,
    payload: SignalAssignmentCreateRequest,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.create_assignment(
        definition_id=definition_id,
        farm_id=payload.farm_id,
        block_id=payload.block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


@router.delete(
    "/signals/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove a signal assignment.",
)
async def delete_assignment(
    assignment_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    await service.delete_assignment(
        assignment_id=assignment_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )


# ---------- Observations -------------------------------------------------


def _ensure_farm_capability(context: RequestContext, capability: str, farm_id: UUID) -> None:
    """Body-driven farm-scoped check. The route-level
    ``requires_capability(farm_id_param=...)`` reads from path/query
    params, but ``farm_id`` here lives in the JSON body â€” so the route
    handler authenticates first, parses the body, then checks the
    farm scope explicitly."""
    if not has_capability(context, capability, farm_id=farm_id):
        from app.shared.rbac.check import PermissionDeniedError

        raise PermissionDeniedError(capability, farm_id=farm_id)


@router.post(
    "/signals/observations:upload-init",
    response_model=SignalAttachmentInitResponse,
    summary="Begin a signal-observation attachment upload (presigned PUT).",
)
async def init_attachment_upload(
    payload: SignalAttachmentInitRequest,
    context: RequestContext = Depends(get_current_context),
    service: SignalsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    _ensure_farm_capability(context, "signal.record", payload.farm_id)
    tenant_id = await _resolve_tenant_id(schema=schema, tenant_session=tenant_session)
    return await service.init_attachment_upload(
        signal_definition_id=payload.signal_definition_id,
        farm_id=payload.farm_id,
        content_type=payload.content_type,
        content_length=payload.content_length,
        filename=payload.filename,
        tenant_id=tenant_id,
    )


@router.post(
    "/signals/definitions/{definition_id}/observations",
    response_model=SignalObservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a signal observation.",
)
async def create_observation(
    definition_id: UUID,
    payload: SignalObservationCreateRequest,
    context: RequestContext = Depends(get_current_context),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    _ensure_farm_capability(context, "signal.record", payload.farm_id)
    if context.user_id is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="User context required",
            detail="Recording an observation requires an authenticated user.",
            type_="https://agripulse.cloud/problems/user-required",
        )
    return await service.create_observation(
        definition_id=definition_id,
        time=payload.time,
        farm_id=payload.farm_id,
        block_id=payload.block_id,
        value_numeric=payload.value_numeric,
        value_categorical=payload.value_categorical,
        value_event=payload.value_event,
        value_boolean=payload.value_boolean,
        value_geopoint=payload.value_geopoint,
        attachment_s3_key=payload.attachment_s3_key,
        notes=payload.notes,
        recorded_by=context.user_id,
        tenant_schema=schema,
    )


@router.get(
    "/signals/observations",
    response_model=list[SignalObservationResponse],
    summary="List signal observations.",
)
async def list_observations(
    signal_definition_id: UUID | None = Query(default=None),
    farm_id: UUID | None = Query(default=None),
    block_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(
        await service.list_observations(
            signal_definition_id=signal_definition_id,
            farm_id=farm_id,
            block_id=block_id,
            since=since,
            until=until,
            limit=limit,
        )
    )
