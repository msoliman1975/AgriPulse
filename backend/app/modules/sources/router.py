"""Sources library routes (decision D27).

  GET    /api/v1/sources                          list (q, document, include_inactive)
  GET    /api/v1/sources/documents                the source lists imported
  GET    /api/v1/sources/links?entity_type=&entity_key=   what an entity cites
  GET    /api/v1/sources/alias/{document}/{n}     resolve "[n]" in a document
  GET    /api/v1/sources/{id}                     one source, its aliases and links
  POST   /api/v1/admin/sources                    create            platform.manage_crops
  PATCH  /api/v1/admin/sources/{id}               edit or retire    platform.manage_crops
  POST   /api/v1/admin/sources/{id}/links         link an entity    platform.manage_crops
  DELETE /api/v1/admin/source-links/{link_id}     unlink            platform.manage_crops

Reads are open to every signed-in user: a source is published reference
material and the "Sources" marker shows it to growers. Writes are curated
with the crop catalogue, so they share its capability, and are audited.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.modules.audit import get_audit_service
from app.modules.sources.schemas import (
    EntityType,
    SourceCreateRequest,
    SourceDetail,
    SourceDocument,
    SourceLink,
    SourceLinkRequest,
    SourceSummary,
    SourceUpdateRequest,
)
from app.modules.sources.service import DuplicateDoiError, SourceNotFoundError, SourcesService
from app.shared.auth.context import RequestContext
from app.shared.auth.middleware import get_current_context
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability

router = APIRouter(tags=["sources"])

_WRITE = "platform.manage_crops"


def _service(session: AsyncSession = Depends(get_admin_db_session)) -> SourcesService:
    return SourcesService(session)


def _not_found(what: str) -> APIError:
    return APIError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Source not found",
        detail=f"No source matches {what}.",
        type_="https://agripulse.cloud/problems/source-not-found",
    )


def _duplicate(doi: str) -> APIError:
    return APIError(
        status_code=status.HTTP_409_CONFLICT,
        title="DOI already in the library",
        detail=f"A source with DOI {doi} already exists; link that one instead.",
        type_="https://agripulse.cloud/problems/source-duplicate-doi",
    )


@router.get("/api/v1/sources", response_model=list[SourceSummary])
async def list_sources(
    q: str | None = Query(default=None, max_length=200),
    document: str | None = Query(default=None, max_length=100),
    include_inactive: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: RequestContext = Depends(get_current_context),
    service: SourcesService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_sources(
        q=q,
        document_code=document,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )


@router.get("/api/v1/sources/documents", response_model=list[SourceDocument])
async def list_documents(
    context: RequestContext = Depends(get_current_context),
    service: SourcesService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.list_documents()


@router.get("/api/v1/sources/links", response_model=list[SourceLink])
async def links_for_entity(
    entity_type: EntityType,
    entity_key: str = Query(min_length=1, max_length=255),
    context: RequestContext = Depends(get_current_context),
    service: SourcesService = Depends(_service),
) -> list[dict[str, Any]]:
    del context
    return await service.links_for(entity_type=entity_type, entity_key=entity_key)


@router.get("/api/v1/sources/alias/{document_code}/{ref_number}", response_model=SourceDetail)
async def resolve_alias(
    document_code: str,
    ref_number: int,
    context: RequestContext = Depends(get_current_context),
    service: SourcesService = Depends(_service),
) -> dict[str, Any]:
    del context
    try:
        return await service.resolve_alias(document_code, ref_number)
    except SourceNotFoundError as exc:
        raise _not_found(f"[{ref_number}] in {document_code}") from exc


@router.get("/api/v1/sources/{source_id}", response_model=SourceDetail)
async def get_source(
    source_id: UUID,
    context: RequestContext = Depends(get_current_context),
    service: SourcesService = Depends(_service),
) -> dict[str, Any]:
    del context
    try:
        return await service.get_source(source_id)
    except SourceNotFoundError as exc:
        raise _not_found(str(source_id)) from exc


@router.post(
    "/api/v1/admin/sources", response_model=SourceDetail, status_code=status.HTTP_201_CREATED
)
async def create_source(
    payload: SourceCreateRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: SourcesService = Depends(_service),
) -> dict[str, Any]:
    fields = payload.model_dump(exclude_none=True)
    try:
        created = await service.create_source(fields, context.user_id)
    except DuplicateDoiError as exc:
        raise _duplicate(str(exc)) from exc
    await get_audit_service().record_archive(
        event_type="platform.source_created",
        actor_user_id=context.user_id,
        subject_kind="source",
        subject_id=created["id"],
        details={"citation": created["citation"], "doi": created["doi"]},
    )
    return created


@router.patch("/api/v1/admin/sources/{source_id}", response_model=SourceDetail)
async def update_source(
    source_id: UUID,
    payload: SourceUpdateRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: SourcesService = Depends(_service),
) -> dict[str, Any]:
    fields = payload.model_dump(exclude_unset=True)
    try:
        updated = await service.update_source(source_id, fields, context.user_id)
    except SourceNotFoundError as exc:
        raise _not_found(str(source_id)) from exc
    except DuplicateDoiError as exc:
        raise _duplicate(str(exc)) from exc
    await get_audit_service().record_archive(
        event_type="platform.source_updated",
        actor_user_id=context.user_id,
        subject_kind="source",
        subject_id=source_id,
        details={"fields": sorted(fields)},
    )
    return updated


@router.post(
    "/api/v1/admin/sources/{source_id}/links",
    response_model=SourceLink,
    status_code=status.HTTP_201_CREATED,
)
async def link_source(
    source_id: UUID,
    payload: SourceLinkRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: SourcesService = Depends(_service),
) -> dict[str, Any]:
    try:
        link = await service.link(source_id, payload.model_dump(), context.user_id)
    except SourceNotFoundError as exc:
        raise _not_found(str(source_id)) from exc
    await get_audit_service().record_archive(
        event_type="platform.source_linked",
        actor_user_id=context.user_id,
        subject_kind="source",
        subject_id=source_id,
        details=payload.model_dump(),
    )
    return link


@router.delete("/api/v1/admin/source-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_source(
    link_id: UUID,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: SourcesService = Depends(_service),
) -> Response:
    try:
        removed = await service.unlink(link_id)
    except SourceNotFoundError as exc:
        raise _not_found(str(link_id)) from exc
    await get_audit_service().record_archive(
        event_type="platform.source_unlinked",
        actor_user_id=context.user_id,
        subject_kind="source",
        subject_id=removed["source_id"],
        details={k: str(v) for k, v in removed.items()},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
