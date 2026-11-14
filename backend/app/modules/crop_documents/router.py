"""Crop documents routes (decision D29).

  GET    /api/v1/admin/crop-documents?crop_path=        editions on a path + inherited  platform.read
  POST   /api/v1/admin/crop-documents                   upload (multipart)    platform.manage_crops
  PATCH  /api/v1/admin/crop-documents/{id}              edit or retire        platform.manage_crops
  GET    /api/v1/admin/crop-documents/{id}/link         view/download link    platform.read
  GET    /api/v1/blocks/{block_id}/crop-documents       what the block shows  crop_document.download
  GET    /api/v1/blocks/{block_id}/crop-documents/{id}/link                   crop_document.download

Uploads are curated with the crop catalogue, so they share its capability
and are audited. Tenant reads need `crop_document.download` on the block's
farm (TenantOwner and TenantAdmin by default; any other role through the RBAC
matrix). A caller without it gets 404 for the block, as the attachment
routes do, so a block id cannot be probed.

Files are uploaded through the API (multipart), not presigned PUTs: the
uploader is a platform admin, the files are manuals, and one request that
both stores the bytes and writes the row is the call an operator can script.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.logging import get_logger
from app.modules.audit import get_audit_service
from app.modules.crop_documents.schemas import (
    MAX_DOCUMENT_BYTES,
    BlockCropDocuments,
    CropDocument,
    CropDocumentFields,
    CropDocumentLink,
    CropDocumentUpdateRequest,
    CropDocumentUploaded,
    Disposition,
    DocumentKind,
    DocumentLanguage,
)
from app.modules.crop_documents.service import (
    BlockCropLookup,
    CropDocumentNotFoundError,
    CropDocumentsService,
    UnknownCropPathError,
    UnsupportedFileError,
)
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session, get_db_session
from app.shared.rbac.check import has_capability, requires_capability

router = APIRouter(tags=["crop-documents"])
_log = get_logger(__name__)

_WRITE = "platform.manage_crops"
_READ_ADMIN = "platform.read"
DOWNLOAD = "crop_document.download"


def _service(session: AsyncSession = Depends(get_admin_db_session)) -> CropDocumentsService:
    return CropDocumentsService(session)


class _FarmsLookup:
    """`BlockCropLookup` over the farms module's public service."""

    def __init__(self, tenant_session: AsyncSession, public_session: AsyncSession) -> None:
        from app.modules.farms.service import get_farm_service

        self._farms = get_farm_service(tenant_session=tenant_session, public_session=public_session)

    async def farm_id_of(self, block_id: UUID) -> UUID:
        # Raises the farms module's 404 when the block is not in this tenant.
        block = await self._farms.get_block(block_id=block_id, preferred_unit="hectare")
        farm_id: UUID = block["farm_id"]
        return farm_id

    async def current_crop_path(self, block_id: UUID) -> str | None:
        for assignment in await self._farms.list_block_crops(block_id=block_id):
            if assignment.get("is_active_now") and assignment.get("crop_path"):
                path: str = assignment["crop_path"]
                return path
        return None


def _lookup(
    tenant_session: AsyncSession = Depends(get_db_session),
    public_session: AsyncSession = Depends(get_admin_db_session),
) -> BlockCropLookup:
    return _FarmsLookup(tenant_session, public_session)


def _problem(code: int, title: str, detail: str, slug: str) -> APIError:
    return APIError(
        status_code=code,
        title=title,
        detail=detail,
        type_=f"https://agripulse.cloud/problems/{slug}",
    )


def _not_found(what: object) -> APIError:
    return _problem(
        status.HTTP_404_NOT_FOUND,
        "Crop document not found",
        f"No crop document matches {what}.",
        "crop-document-not-found",
    )


async def _require_block_access(
    context: RequestContext, block_id: UUID, lookup: BlockCropLookup
) -> None:
    if context.tenant_schema is None:
        raise _problem(
            status.HTTP_403_FORBIDDEN,
            "Tenant context required",
            "This endpoint requires a tenant-scoped JWT.",
            "tenant-required",
        )
    farm_id = await lookup.farm_id_of(block_id)
    if not has_capability(context, DOWNLOAD, farm_id=farm_id):
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Block not found",
            f"No block with id {block_id} in this tenant.",
            "block-not-found",
        )


# ---- Admin ------------------------------------------------------------------


@router.get("/api/v1/admin/crop-documents", response_model=list[CropDocument])
async def list_crop_documents(
    crop_path: str = Query(min_length=1, max_length=200),
    context: RequestContext = Depends(requires_capability(_READ_ADMIN)),
    service: CropDocumentsService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_for_admin(crop_path)


@router.post(
    "/api/v1/admin/crop-documents",
    response_model=CropDocumentUploaded,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a crop document, or a new edition of one (multipart).",
)
async def upload_crop_document(
    file: UploadFile = File(
        ..., description="The document. pdf, doc(x), xls(x), ppt(x), txt, md, csv."
    ),
    crop_path: str = Form(...),
    document_code: str = Form(...),
    title_en: str = Form(...),
    title_ar: str = Form(...),
    language: DocumentLanguage = Form(...),
    kind: DocumentKind = Form(...),
    edition: str = Form(...),
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropDocumentsService = Depends(_service),
) -> dict[str, Any]:
    try:
        fields = CropDocumentFields(
            crop_path=crop_path,
            document_code=document_code,
            title_en=title_en,
            title_ar=title_ar,
            language=language,
            kind=kind,
            edition=edition,
        )
    except ValidationError as exc:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid crop document",
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()),
            "crop-document-invalid",
        ) from exc
    # One byte past the limit is enough to know it is too large.
    body = await file.read(MAX_DOCUMENT_BYTES + 1)
    filename = (file.filename or "").strip() or "document"
    try:
        created = await service.upload(fields, filename=filename, body=body, actor=context.user_id)
    except UnsupportedFileError as exc:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "File not accepted",
            str(exc),
            "crop-document-file-rejected",
        ) from exc
    except UnknownCropPathError as exc:
        raise _problem(
            status.HTTP_404_NOT_FOUND,
            "Unknown crop path",
            f"No crop, variety or strain has path {fields.crop_path!r}.",
            "crop-path-unknown",
        ) from exc
    await get_audit_service().record_archive(
        event_type="platform.crop_document_uploaded",
        actor_user_id=context.user_id,
        subject_kind="crop_document",
        subject_id=created["id"],
        details={
            "crop_path": created["crop_path"],
            "document_code": created["document_code"],
            "edition": created["edition"],
            "language": created["language"],
            "size_bytes": created["size_bytes"],
            "sha256": created["sha256"],
            "superseded_id": str(created["superseded_id"]) if created["superseded_id"] else None,
        },
    )
    return created


@router.patch("/api/v1/admin/crop-documents/{document_id}", response_model=CropDocument)
async def update_crop_document(
    document_id: UUID,
    payload: CropDocumentUpdateRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropDocumentsService = Depends(_service),
) -> dict[str, Any]:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Nothing to change",
            "Send at least one field.",
            "crop-document-invalid",
        )
    try:
        updated = await service.update(document_id, fields, context.user_id)
    except CropDocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    await get_audit_service().record_archive(
        event_type="platform.crop_document_updated",
        actor_user_id=context.user_id,
        subject_kind="crop_document",
        subject_id=document_id,
        details={
            "fields": sorted(fields),
            **({"retired": fields["retired"]} if "retired" in fields else {}),
        },
    )
    return updated


@router.get("/api/v1/admin/crop-documents/{document_id}/link", response_model=CropDocumentLink)
async def admin_crop_document_link(
    document_id: UUID,
    disposition: Disposition = "attachment",
    context: RequestContext = Depends(requires_capability(_READ_ADMIN)),
    service: CropDocumentsService = Depends(_service),
) -> dict[str, Any]:
    del context
    try:
        return await service.admin_link(document_id, disposition)
    except CropDocumentNotFoundError as exc:
        raise _not_found(document_id) from exc


# ---- Tenant -----------------------------------------------------------------


@router.get("/api/v1/blocks/{block_id}/crop-documents", response_model=BlockCropDocuments)
async def list_block_crop_documents(
    block_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: CropDocumentsService = Depends(_service),
    lookup: BlockCropLookup = Depends(_lookup),
) -> dict[str, Any]:
    await _require_block_access(context, block_id, lookup)
    return await service.for_block(block_id, lookup)


@router.get(
    "/api/v1/blocks/{block_id}/crop-documents/{document_id}/link",
    response_model=CropDocumentLink,
)
async def block_crop_document_link(
    block_id: UUID,
    document_id: UUID,
    disposition: Disposition = "attachment",
    context: RequestContext = Depends(get_current_context),
    service: CropDocumentsService = Depends(_service),
    lookup: BlockCropLookup = Depends(_lookup),
) -> dict[str, Any]:
    await _require_block_access(context, block_id, lookup)
    try:
        link = await service.block_link(block_id, document_id, disposition, lookup)
    except CropDocumentNotFoundError as exc:
        raise _not_found(document_id) from exc
    # Every production action is logged; a download is the one a tenant
    # takes here. The link itself is not logged: it is a bearer credential.
    _log.info(
        "crop_document_link_issued",
        tenant_id=str(context.tenant_id),
        user_id=str(context.user_id),
        block_id=str(block_id),
        document_id=str(document_id),
        disposition=link["disposition"],
    )
    return link
