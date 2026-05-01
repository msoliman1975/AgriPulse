"""FastAPI routes for the farms module.

The router is mounted under /api/v1 by the app factory. Sessions:

  * `get_db_session` is tenant-scoped (search_path = tenant_<uuid>, public).
  * `get_admin_db_session` is public-only — needed for `farm_scopes` ops
    that target `public.farm_scopes` regardless of search_path.

Two distinct sessions means two transactions per request (tenant + public).
Audit also opens its own. This is the same pattern used by the tenancy
admin endpoint (which delegates schema bootstrap into a thread executor)
and is acceptable for the current consistency requirements: audit failures
are logged loudly but do not roll back the operation, and farm_scopes
inconsistencies are caught by the cross-schema FK consistency-check job
that PR-C will add.

Note: this module deliberately does NOT use ``from __future__ import
annotations``. FastAPI/Pydantic v2's TypeAdapter cannot resolve string
annotations like ``request: Request`` and silently demotes them to
required query parameters, which breaks OpenAPI generation and POST
route validation.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.schemas import (
    AttachmentFinalizeRequest,
    AttachmentResponse,
    AttachmentUploadInitRequest,
    AttachmentUploadInitResponse,
    AutoGridRequest,
    AutoGridResponse,
    BlockCreateRequest,
    BlockCropAssignRequest,
    BlockCropResponse,
    BlockDetailResponse,
    BlockResponse,
    BlockUpdateRequest,
    CropResponse,
    CropVarietyResponse,
    FarmCreateRequest,
    FarmDetailResponse,
    FarmMemberAssignRequest,
    FarmMemberResponse,
    FarmResponse,
    FarmUpdateRequest,
)
from app.modules.farms.service import FarmService, get_farm_service
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.pagination import (
    CursorPage,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)
from app.shared.rbac.check import requires_capability

router = APIRouter(prefix="/api/v1", tags=["farms"])


def _service(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> FarmService:
    return get_farm_service(
        tenant_session=tenant_session,
        public_session=public_session,
    )


def _correlation_id(request: Request) -> UUID | None:
    cid = getattr(request.state, "correlation_id", None)
    if isinstance(cid, str):
        try:
            return UUID(cid)
        except ValueError:
            return None
    if isinstance(cid, UUID):
        return cid
    return None


def _ensure_tenant(context: RequestContext) -> str:
    schema = context.tenant_schema
    if schema is None:
        # Defense-in-depth — the JWT middleware already gates this for
        # tenant-scoped capabilities, so platform-only callers should not
        # reach here.
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://missionagre.io/problems/tenant-required",
        )
    return schema


# ---------- Farms -----------------------------------------------------------


@router.post(
    "/farms",
    response_model=FarmDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a farm.",
)
async def create_farm(
    payload: FarmCreateRequest,
    request: Request,
    context: RequestContext = Depends(requires_capability("farm.create")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.create_farm(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        boundary=payload.boundary,
        elevation_m=payload.elevation_m,
        governorate=payload.governorate,
        district=payload.district,
        nearest_city=payload.nearest_city,
        address_line=payload.address_line,
        farm_type=payload.farm_type,
        ownership_type=payload.ownership_type,
        primary_water_source=payload.primary_water_source,
        established_date=payload.established_date,
        tags=payload.tags,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        preferred_unit=context.preferred_unit,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/farms",
    response_model=CursorPage[FarmResponse],
    summary="List farms in the current tenant.",
)
async def list_farms(
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    governorate: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    context: RequestContext = Depends(requires_capability("farm.read")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    capped_limit = clamp_limit(limit)
    after = decode_cursor(cursor)
    items = await service.list_farms(
        after=after,
        limit=capped_limit,
        status_filter=status_filter,
        governorate=governorate,
        tag=tag,
        include_archived=include_archived,
        preferred_unit=context.preferred_unit,
    )
    next_cursor = encode_cursor(items[-1]["id"]) if len(items) == capped_limit else None
    return {"items": items, "next_cursor": next_cursor}


@router.get(
    "/farms/{farm_id}",
    response_model=FarmDetailResponse,
    summary="Get a farm by id.",
)
async def get_farm(
    farm_id: UUID,
    context: RequestContext = Depends(requires_capability("farm.read", farm_id_param="farm_id")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    return await service.get_farm(farm_id=farm_id, preferred_unit=context.preferred_unit)


@router.patch(
    "/farms/{farm_id}",
    response_model=FarmDetailResponse,
    summary="Update a farm.",
)
async def update_farm(
    farm_id: UUID,
    payload: FarmUpdateRequest,
    request: Request,
    context: RequestContext = Depends(requires_capability("farm.update", farm_id_param="farm_id")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    data = payload.model_dump(exclude_unset=True)
    new_boundary = data.pop("boundary", None)
    return await service.update_farm(
        farm_id=farm_id,
        changes=data,
        new_boundary=new_boundary,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        preferred_unit=context.preferred_unit,
        correlation_id=_correlation_id(request),
    )


@router.delete(
    "/farms/{farm_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-archive a farm.",
    response_model=None,
)
async def archive_farm(
    farm_id: UUID,
    request: Request,
    context: RequestContext = Depends(requires_capability("farm.delete", farm_id_param="farm_id")),
    service: FarmService = Depends(_service),
) -> None:
    schema = _ensure_tenant(context)
    await service.archive_farm(
        farm_id=farm_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


# ---------- Blocks ----------------------------------------------------------


@router.post(
    "/farms/{farm_id}/blocks",
    response_model=BlockDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a block in a farm.",
)
async def create_block(
    farm_id: UUID,
    payload: BlockCreateRequest,
    request: Request,
    context: RequestContext = Depends(requires_capability("block.create", farm_id_param="farm_id")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.create_block(
        farm_id=farm_id,
        code=payload.code,
        name=payload.name,
        boundary=payload.boundary,
        elevation_m=payload.elevation_m,
        irrigation_system=payload.irrigation_system,
        irrigation_source=payload.irrigation_source,
        soil_texture=payload.soil_texture,
        salinity_class=payload.salinity_class,
        soil_ph=payload.soil_ph,
        responsible_user_id=payload.responsible_user_id,
        notes=payload.notes,
        tags=payload.tags,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        preferred_unit=context.preferred_unit,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/farms/{farm_id}/blocks",
    response_model=CursorPage[BlockResponse],
    summary="List blocks in a farm.",
)
async def list_blocks(
    farm_id: UUID,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    irrigation_system: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    context: RequestContext = Depends(requires_capability("block.read", farm_id_param="farm_id")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    capped_limit = clamp_limit(limit)
    items = await service.list_blocks(
        farm_id=farm_id,
        after=decode_cursor(cursor),
        limit=capped_limit,
        status_filter=status_filter,
        irrigation_system=irrigation_system,
        include_archived=include_archived,
        preferred_unit=context.preferred_unit,
    )
    next_cursor = encode_cursor(items[-1]["id"]) if len(items) == capped_limit else None
    return {"items": items, "next_cursor": next_cursor}


@router.get(
    "/blocks/{block_id}",
    response_model=BlockDetailResponse,
    summary="Get a block by id.",
)
async def get_block(
    block_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    # Block routes do not have farm_id in the path — RBAC verifies the
    # caller has block.read on *some* farm; the service then 404s if the
    # block belongs to a farm the caller cannot see. (For MVP we
    # delegate to tenant-scoped capability; per-farm RBAC on block
    # reads is enforced by the front-end's nested-route paths.)
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "block.read", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)
    return block


@router.patch(
    "/blocks/{block_id}",
    response_model=BlockDetailResponse,
    summary="Update a block.",
)
async def update_block(
    block_id: UUID,
    payload: BlockUpdateRequest,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    # We need to know which farm this block lives in to do per-farm RBAC.
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    schema = _ensure_tenant(context)
    block_existing = await service.get_block(
        block_id=block_id, preferred_unit=context.preferred_unit
    )
    farm_id = block_existing["farm_id"]

    data = payload.model_dump(exclude_unset=True)
    new_boundary = data.pop("boundary", None)
    needs_geom_cap = new_boundary is not None
    needs_meta_cap = bool(data)

    if needs_geom_cap and not has_capability(context, "block.update_geometry", farm_id=farm_id):
        raise BlockNotFoundError(block_id)
    if needs_meta_cap and not has_capability(context, "block.update_metadata", farm_id=farm_id):
        raise BlockNotFoundError(block_id)

    return await service.update_block(
        block_id=block_id,
        changes=data,
        new_boundary=new_boundary,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        preferred_unit=context.preferred_unit,
        correlation_id=_correlation_id(request),
    )


@router.delete(
    "/blocks/{block_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-archive a block.",
    response_model=None,
)
async def archive_block(
    block_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> None:
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    schema = _ensure_tenant(context)
    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "block.delete", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)

    await service.archive_block(
        block_id=block_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


# ---------- Auto-grid -------------------------------------------------------


@router.post(
    "/farms/{farm_id}/blocks/auto-grid",
    response_model=AutoGridResponse,
    summary="Compute candidate block polygons by tiling the farm in a grid.",
)
async def auto_grid(
    farm_id: UUID,
    payload: AutoGridRequest,
    context: RequestContext = Depends(requires_capability("block.create", farm_id_param="farm_id")),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    return await service.auto_grid(farm_id=farm_id, cell_size_m=payload.cell_size_m)


# ---------- Block crops -----------------------------------------------------


@router.post(
    "/blocks/{block_id}/crop-assignments",
    response_model=BlockCropResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a crop to a block.",
)
async def assign_block_crop(
    block_id: UUID,
    payload: BlockCropAssignRequest,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    schema = _ensure_tenant(context)
    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "crop_assignment.create", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)

    return await service.assign_block_crop(
        block_id=block_id,
        crop_id=payload.crop_id,
        crop_variety_id=payload.crop_variety_id,
        season_label=payload.season_label,
        planting_date=payload.planting_date,
        expected_harvest_start=payload.expected_harvest_start,
        expected_harvest_end=payload.expected_harvest_end,
        plant_density_per_ha=payload.plant_density_per_ha,
        row_spacing_m=payload.row_spacing_m,
        plant_spacing_m=payload.plant_spacing_m,
        notes=payload.notes,
        make_current=payload.make_current,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/blocks/{block_id}/crop-assignments",
    response_model=list[BlockCropResponse],
    summary="List crop assignments for a block.",
)
async def list_block_crops(
    block_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> list[dict[str, Any]]:
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "block.read", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)

    return await service.list_block_crops(block_id=block_id)


# ---------- Members ---------------------------------------------------------


@router.post(
    "/farms/{farm_id}/members",
    response_model=FarmMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a tenant member to a farm with a per-farm role.",
)
async def assign_member(
    farm_id: UUID,
    payload: FarmMemberAssignRequest,
    request: Request,
    context: RequestContext = Depends(
        requires_capability("role.assign_farm", farm_id_param="farm_id")
    ),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    if context.tenant_id is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="role.assign_farm requires a tenant-scoped JWT.",
            type_="https://missionagre.io/problems/tenant-required",
        )

    return await service.assign_member(
        farm_id=farm_id,
        membership_id=payload.membership_id,
        role=payload.role,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        tenant_id=context.tenant_id,
        correlation_id=_correlation_id(request),
    )


@router.delete(
    "/farms/{farm_id}/members/{farm_scope_id}",
    response_model=FarmMemberResponse,
    summary="Revoke a per-farm role assignment.",
)
async def revoke_member(
    farm_id: UUID,
    farm_scope_id: UUID,
    request: Request,
    context: RequestContext = Depends(
        requires_capability("role.assign_farm", farm_id_param="farm_id")
    ),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.revoke_member(
        farm_id=farm_id,
        farm_scope_id=farm_scope_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/farms/{farm_id}/members",
    response_model=list[FarmMemberResponse],
    summary="List members assigned to a farm.",
)
async def list_members(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.member.read", farm_id_param="farm_id")
    ),
    service: FarmService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_members(farm_id=farm_id)


# ---------- Attachments ----------------------------------------------------


def _require_tenant_id(context: RequestContext) -> UUID:
    if context.tenant_id is None:
        from app.core.errors import APIError

        raise APIError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Tenant context required",
            detail="This endpoint requires a tenant-scoped JWT.",
            type_="https://missionagre.io/problems/tenant-required",
        )
    return context.tenant_id


@router.post(
    "/farms/{farm_id}/attachments:init",
    response_model=AttachmentUploadInitResponse,
    summary="Begin a farm-attachment upload (returns a presigned PUT URL).",
)
async def init_farm_attachment(
    farm_id: UUID,
    payload: AttachmentUploadInitRequest,
    context: RequestContext = Depends(
        requires_capability("farm.attachment.write", farm_id_param="farm_id")
    ),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    _ensure_tenant(context)
    tenant_id = _require_tenant_id(context)
    return await service.init_farm_attachment_upload(
        farm_id=farm_id,
        kind=payload.kind,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        tenant_id=tenant_id,
    )


@router.post(
    "/farms/{farm_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Finalize a farm-attachment upload after the S3 PUT succeeded.",
)
async def finalize_farm_attachment(
    farm_id: UUID,
    payload: AttachmentFinalizeRequest,
    request: Request,
    context: RequestContext = Depends(
        requires_capability("farm.attachment.write", farm_id_param="farm_id")
    ),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    schema = _ensure_tenant(context)
    return await service.finalize_farm_attachment(
        farm_id=farm_id,
        attachment_id=payload.attachment_id,
        s3_key=payload.s3_key,
        kind=payload.kind,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        caption=payload.caption,
        taken_at=payload.taken_at,
        geo_point=payload.geo_point,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/farms/{farm_id}/attachments",
    response_model=list[AttachmentResponse],
    summary="List farm attachments.",
)
async def list_farm_attachments(
    farm_id: UUID,
    context: RequestContext = Depends(
        requires_capability("farm.attachment.read", farm_id_param="farm_id")
    ),
    service: FarmService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_farm_attachments(farm_id=farm_id)


@router.delete(
    "/farms/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a farm attachment (soft) and remove the S3 object.",
)
async def delete_farm_attachment(
    attachment_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> None:
    from app.modules.farms.errors import FarmAttachmentNotFoundError
    from app.shared.rbac.check import has_capability

    schema = _ensure_tenant(context)
    # Per-farm RBAC: read the row, check the owning farm.
    existing = await _peek_farm_attachment(service, attachment_id)
    if existing is None or not has_capability(
        context, "farm.attachment.write", farm_id=existing["owner_id"]
    ):
        raise FarmAttachmentNotFoundError(attachment_id)
    await service.delete_farm_attachment(
        attachment_id=attachment_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.post(
    "/blocks/{block_id}/attachments:init",
    response_model=AttachmentUploadInitResponse,
    summary="Begin a block-attachment upload (returns a presigned PUT URL).",
)
async def init_block_attachment(
    block_id: UUID,
    payload: AttachmentUploadInitRequest,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    _ensure_tenant(context)
    tenant_id = _require_tenant_id(context)
    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "block.attachment.write", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)
    return await service.init_block_attachment_upload(
        block_id=block_id,
        kind=payload.kind,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        tenant_id=tenant_id,
    )


@router.post(
    "/blocks/{block_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Finalize a block-attachment upload after the S3 PUT succeeded.",
)
async def finalize_block_attachment(
    block_id: UUID,
    payload: AttachmentFinalizeRequest,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> dict[str, Any]:
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    schema = _ensure_tenant(context)
    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "block.attachment.write", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)
    return await service.finalize_block_attachment(
        block_id=block_id,
        attachment_id=payload.attachment_id,
        s3_key=payload.s3_key,
        kind=payload.kind,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        caption=payload.caption,
        taken_at=payload.taken_at,
        geo_point=payload.geo_point,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


@router.get(
    "/blocks/{block_id}/attachments",
    response_model=list[AttachmentResponse],
    summary="List block attachments.",
)
async def list_block_attachments(
    block_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> list[dict[str, Any]]:
    from app.modules.farms.errors import BlockNotFoundError
    from app.shared.rbac.check import has_capability

    _ensure_tenant(context)
    block = await service.get_block(block_id=block_id, preferred_unit=context.preferred_unit)
    if not has_capability(context, "block.attachment.read", farm_id=block["farm_id"]):
        raise BlockNotFoundError(block_id)
    return await service.list_block_attachments(block_id=block_id)


@router.delete(
    "/blocks/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a block attachment (soft) and remove the S3 object.",
)
async def delete_block_attachment(
    attachment_id: UUID,
    request: Request,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> None:
    from app.modules.farms.errors import BlockAttachmentNotFoundError
    from app.shared.rbac.check import has_capability

    schema = _ensure_tenant(context)
    existing = await _peek_block_attachment(service, attachment_id)
    if existing is None:
        raise BlockAttachmentNotFoundError(attachment_id)
    block = await service.get_block(
        block_id=existing["owner_id"], preferred_unit=context.preferred_unit
    )
    if not has_capability(context, "block.attachment.write", farm_id=block["farm_id"]):
        raise BlockAttachmentNotFoundError(attachment_id)
    await service.delete_block_attachment(
        attachment_id=attachment_id,
        actor_user_id=context.user_id,
        tenant_schema=schema,
        correlation_id=_correlation_id(request),
    )


async def _peek_farm_attachment(service: FarmService, attachment_id: UUID) -> dict[str, Any] | None:
    """Read just enough of the attachment row to resolve its owning farm.

    Bypasses the public service surface — uses the underlying repo so we
    don't presign a download URL on a row we're about to delete.
    """
    repo = getattr(service, "_repo", None)
    if repo is None:
        return None
    return await repo.get_farm_attachment(attachment_id=attachment_id)


async def _peek_block_attachment(
    service: FarmService, attachment_id: UUID
) -> dict[str, Any] | None:
    repo = getattr(service, "_repo", None)
    if repo is None:
        return None
    return await repo.get_block_attachment(attachment_id=attachment_id)


# ---------- Crop catalog (read-only) ---------------------------------------


@router.get(
    "/crops",
    response_model=list[CropResponse],
    summary="List active crops in the public catalog.",
)
async def list_crops(
    category: str | None = Query(default=None),
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_crops(category=category)


@router.get(
    "/crops/{crop_id}/varieties",
    response_model=list[CropVarietyResponse],
    summary="List active varieties for a crop.",
)
async def list_crop_varieties(
    crop_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: FarmService = Depends(_service),
) -> list[dict[str, Any]]:
    _ensure_tenant(context)
    return await service.list_crop_varieties(crop_id=crop_id)
