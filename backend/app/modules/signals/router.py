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

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict
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
    SignalTemplateCreateRequest,
    SignalTemplateDefinitionMember,
    SignalTemplateObservationCreateRequest,
    SignalTemplateObservationCreateResponse,
    SignalTemplateResponse,
    SignalTemplateUpdateRequest,
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
        aggregation=payload.aggregation,
        aggregation_window_days=payload.aggregation_window_days,
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
    force: bool = Query(
        default=False,
        description="Archive even if live trees/templates reference it (CS-13 escape hatch).",
    ),
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> None:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, tenant_session=tenant_session)
    await service.delete_definition(
        definition_id=definition_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        tenant_id=tenant_id,
        force=force,
    )


@router.get(
    "/signals/definitions/{definition_id}/references",
    summary="Decision trees + templates referencing this definition (CS-13).",
)
async def get_definition_references(
    definition_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, list[dict[str, str]]]:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, tenant_session=tenant_session)
    return await service.get_definition_references(
        definition_id=definition_id, tenant_id=tenant_id
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


# ---------- Templates (CS-2/3) --------------------------------------------
#
# Templates group N SignalDefinitions for the entry UX. The engine
# still sees flat per-definition observations; templates are a
# tenant-admin concept gated on signal.define (no per-farm grant).


class SignalTemplateWithMembersResponse(BaseModel):
    """Template detail + ordered members. The detail endpoint returns
    this; the list endpoint returns SignalTemplateResponse only
    (members fetched on demand)."""

    model_config = ConfigDict(from_attributes=True)

    template: SignalTemplateResponse
    members: list[SignalTemplateDefinitionMember]


@router.get(
    "/signals/templates",
    response_model=list[SignalTemplateResponse],
    summary="List signal templates in the current tenant.",
)
async def list_templates(
    include_inactive: bool = Query(default=False),
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return list(await service.list_templates(include_inactive=include_inactive))


@router.post(
    "/signals/templates",
    response_model=SignalTemplateWithMembersResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a signal template (tenant admins).",
)
async def create_template(
    payload: SignalTemplateCreateRequest,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    tpl, members = await service.create_template(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        members=tuple(payload.members),
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
    return {"template": tpl, "members": list(members)}


@router.get(
    "/signals/templates/{template_id}",
    response_model=SignalTemplateWithMembersResponse,
    summary="Read a signal template + its ordered members.",
)
async def get_template(
    template_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    tpl, members = await service.get_template(template_id=template_id)
    return {"template": tpl, "members": list(members)}


@router.patch(
    "/signals/templates/{template_id}",
    response_model=SignalTemplateWithMembersResponse,
    summary="Patch a signal template; optionally replace member list.",
)
async def update_template(
    template_id: UUID,
    payload: SignalTemplateUpdateRequest,
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    # `members` is an explicit kwarg on the service; the rest get sent
    # via `updates`. Use exclude_unset so unset == "leave alone" (vs
    # explicit null which an UPDATE can't express for these scalars).
    body = payload.model_dump(exclude_unset=True)
    members_payload = body.pop("members", None)
    members_tuple: tuple[SignalTemplateDefinitionMember, ...] | None
    if members_payload is None and "members" not in payload.model_fields_set:
        members_tuple = None
    else:
        members_tuple = tuple(payload.members or [])
    tpl, members = await service.update_template(
        template_id=template_id,
        updates=body,
        members=members_tuple,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
    return {"template": tpl, "members": list(members)}


@router.delete(
    "/signals/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Soft-delete a signal template.",
)
async def delete_template(
    template_id: UUID,
    force: bool = Query(
        default=False,
        description="Archive even if live trees reference its signals (CS-13 escape hatch).",
    ),
    context: RequestContext = Depends(requires_capability("signal.define")),
    service: SignalsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> None:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, tenant_session=tenant_session)
    await service.delete_template(
        template_id=template_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        tenant_id=tenant_id,
        force=force,
    )


@router.get(
    "/signals/templates/{template_id}/references",
    summary="Decision trees referencing this template's signals (CS-13).",
)
async def get_template_references(
    template_id: UUID,
    context: RequestContext = Depends(requires_capability("signal.read")),
    service: SignalsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, list[dict[str, str]]]:
    schema = _ensure_tenant(context)
    tenant_id = await _resolve_tenant_id(schema=schema, tenant_session=tenant_session)
    return await service.get_template_references(
        template_id=template_id, tenant_id=tenant_id
    )


@router.post(
    "/signals/templates/{template_id}/observations",
    response_model=SignalTemplateObservationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Atomically log N observations against a template (CS-4).",
)
async def create_template_observation(
    template_id: UUID,
    payload: SignalTemplateObservationCreateRequest,
    # signal.record is the same farm-scoped capability used by the
    # one-shot observation endpoint. We auth at the function level
    # then body-check the farm scope because farm_id lives in the JSON
    # body (same pattern as create_observation below).
    context: RequestContext = Depends(get_current_context),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    _ensure_farm_capability(context, "signal.record", payload.farm_id)
    if context.user_id is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="User id required",
            detail="Template-observation submission requires an authenticated user id.",
            type_="https://agripulse.cloud/problems/user-id-required",
        )
    return await service.create_template_observation(
        template_id=template_id,
        farm_id=payload.farm_id,
        block_id=payload.block_id,
        observed_at=payload.observed_at or payload.time,
        location_mode=payload.location_mode,
        location_point=payload.location_point,
        members=tuple(payload.members),
        recorded_by=context.user_id,
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
        location_mode=payload.location_mode,
        location_point=payload.location_point,
        recorded_by=context.user_id,
        tenant_schema=schema,
    )


@router.post(
    "/signals/csv-import",
    status_code=status.HTTP_200_OK,
    response_model=None,
    summary="Strict CSV import for signal observations (CS-7 / CS-12).",
)
async def import_observations_csv(
    farm_id: UUID = Query(..., description="Target farm; all rows are recorded against it."),
    bulk_mode: bool = Query(
        default=False,
        description="Raise the row cap to 50,000 (and size to 50 MB) for backfills. "
        "Requires signal.define + signal.record.",
    ),
    file: UploadFile = File(..., description="UTF-8 CSV file. See module docstring for schema."),
    context: RequestContext = Depends(get_current_context),
    service: SignalsServiceImpl = Depends(_service),
    tenant_session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    schema = _ensure_tenant(context)
    # signal.record on the target farm; per-row farm_id is fixed by
    # the query param so we authorize once instead of N times. Bulk mode
    # is a tenant-admin-level backfill action — additionally gate on
    # signal.define so an everyday operator can't trigger 50k-row imports.
    _ensure_farm_capability(context, "signal.record", farm_id)
    if bulk_mode:
        _ensure_farm_capability(context, "signal.define", farm_id)
    if context.user_id is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="User context required",
            detail="CSV import requires an authenticated user.",
            type_="https://agripulse.cloud/problems/user-required",
        )
    tenant_id = await _resolve_tenant_id(schema=schema, tenant_session=tenant_session)
    csv_bytes = await file.read()
    return await service.import_observations_csv(
        farm_id=farm_id,
        csv_bytes=csv_bytes,
        recorded_by=context.user_id,
        tenant_schema=schema,
        tenant_id=tenant_id,
        bulk_mode=bulk_mode,
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
    # CS-5: lets the FE fetch every sibling of a template submission.
    # The submit endpoint returns the shared template_observation_id;
    # the FE can pass it back through here to hydrate the full group.
    template_observation_id: UUID | None = Query(default=None),
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
            template_observation_id=template_observation_id,
            limit=limit,
        )
    )


@router.delete(
    "/signals/observations",
    status_code=status.HTTP_200_OK,
    summary="Delete all observations in a templated group (CS-11).",
)
async def delete_template_observation(
    template_observation_id: UUID = Query(
        ..., description="Delete every sibling row sharing this id."
    ),
    context: RequestContext = Depends(get_current_context),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, int]:
    schema = _ensure_tenant(context)
    farm_id = await service.get_template_observation_farm(
        template_observation_id=template_observation_id
    )
    if farm_id is None:
        from app.modules.signals.errors import SignalObservationNotFoundError

        raise SignalObservationNotFoundError(template_observation_id)
    _ensure_farm_capability(context, "signal.delete_observation", farm_id)
    deleted = await service.delete_template_observation(
        template_observation_id=template_observation_id,
        farm_id=farm_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
    return {"deleted": deleted}


@router.delete(
    "/signals/observations/{observation_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a single signal observation (CS-11).",
)
async def delete_observation(
    observation_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: SignalsServiceImpl = Depends(_service),
) -> dict[str, int]:
    schema = _ensure_tenant(context)
    obs = await service.get_observation(observation_id=observation_id)
    if obs is None:
        from app.modules.signals.errors import SignalObservationNotFoundError

        raise SignalObservationNotFoundError(observation_id)
    # Farm-scoped capability — resolve farm_id from the row first (it's
    # not in the request), same body-then-check pattern as create.
    _ensure_farm_capability(context, "signal.delete_observation", obs["farm_id"])
    await service.delete_observation(
        observation_id=observation_id,
        farm_id=obs["farm_id"],
        actor_user_id=context.user_id,
        tenant_schema=schema,
    )
    return {"deleted": 1}
