"""Crop image routes (build plan 3.1).

  POST   /api/v1/admin/crops/{crop_id}/image/upload-init           platform.manage_crops
  POST   /api/v1/admin/crops/{crop_id}/image/finalize              platform.manage_crops
  DELETE /api/v1/admin/crops/{crop_id}/image                       platform.manage_crops
  POST   /api/v1/admin/crop-varieties/{variety_id}/image/upload-init
  POST   /api/v1/admin/crop-varieties/{variety_id}/image/finalize
  DELETE /api/v1/admin/crop-varieties/{variety_id}/image
  GET    /api/v1/public/crop-images/{kind}/{owner_id}/{image_id}/{size}.webp   no auth

Uploads are curated with the crop catalogue, so they share its capability
and are audited. The image itself is not sensitive (the same picture for
every tenant) and an ``<img>`` tag cannot send a token, so it is served
from a public route with a year-long cache: every upload has its own key,
so a new image means a new URL, never new bytes behind an old one.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.logging import get_logger
from app.modules.audit import get_audit_service
from app.modules.crop_images.schemas import (
    CropImageFinalizeRequest,
    CropImageResponse,
    CropImageUploadInitRequest,
    CropImageUploadInitResponse,
)
from app.modules.crop_images.service import (
    CropImageOwnerNotFoundError,
    CropImageRejectedError,
    CropImagesService,
    read_rendition,
)
from app.shared.auth.context import RequestContext
from app.shared.db.session import get_admin_db_session
from app.shared.rbac.check import requires_capability
from app.shared.storage import CropImageKind

router = APIRouter(tags=["crop-images"])
_log = get_logger(__name__)

_WRITE = "platform.manage_crops"
#: A year: the URL changes with the image, so the bytes behind one never do.
_CACHE_HIT = "public, max-age=31536000, immutable"


def _service(session: AsyncSession = Depends(get_admin_db_session)) -> CropImagesService:
    return CropImagesService(session)


def _problem(code: int, title: str, detail: str, slug: str) -> APIError:
    return APIError(
        status_code=code,
        title=title,
        detail=detail,
        type_=f"https://agripulse.cloud/problems/{slug}",
    )


def _not_found(kind: CropImageKind, owner_id: UUID) -> APIError:
    what = "crop" if kind == "crops" else "crop variety"
    return _problem(
        status.HTTP_404_NOT_FOUND,
        f"{what.capitalize()} not found",
        f"No {what} with id {owner_id}.",
        "crop-not-found" if kind == "crops" else "crop-variety-not-found",
    )


def _rejected(exc: Exception) -> APIError:
    return _problem(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Image not accepted",
        str(exc),
        "crop-image-rejected",
    )


def _enqueue_renditions(key: str) -> None:
    # Local import keeps Celery out of the module import path, as imagery does.
    from app.modules.crop_images.tasks import make_crop_image_renditions

    try:
        make_crop_image_renditions.delay(key)
    except Exception as exc:  # broker down: the image is saved, renditions can be redone
        _log.warning("crop_image_renditions_not_enqueued", key=key, error=str(exc))


async def _init(
    kind: CropImageKind,
    owner_id: UUID,
    payload: CropImageUploadInitRequest,
    service: CropImagesService,
) -> dict[str, Any]:
    try:
        return await service.init_upload(
            kind, owner_id, content_type=payload.content_type, size_bytes=payload.size_bytes
        )
    except CropImageOwnerNotFoundError as exc:
        raise _not_found(kind, owner_id) from exc
    except CropImageRejectedError as exc:
        raise _rejected(exc) from exc


async def _finalize(
    kind: CropImageKind,
    owner_id: UUID,
    payload: CropImageFinalizeRequest,
    context: RequestContext,
    service: CropImagesService,
) -> dict[str, Any]:
    try:
        result = await service.finalize(kind, owner_id, payload.s3_key)
    except CropImageOwnerNotFoundError as exc:
        raise _not_found(kind, owner_id) from exc
    except CropImageRejectedError as exc:
        raise _rejected(exc) from exc
    await get_audit_service().record_archive(
        event_type="platform.crop_image_updated",
        actor_user_id=context.user_id,
        subject_kind="crop" if kind == "crops" else "crop_variety",
        subject_id=owner_id,
        details={
            "s3_key": payload.s3_key,
            "previous_key": result["previous_key"],
            "size_bytes": result["size_bytes"],
            "content_type": result["content_type"],
        },
    )
    _enqueue_renditions(payload.s3_key)
    return result


async def _remove(
    kind: CropImageKind, owner_id: UUID, context: RequestContext, service: CropImagesService
) -> dict[str, Any]:
    try:
        previous = await service.remove(kind, owner_id)
    except CropImageOwnerNotFoundError as exc:
        raise _not_found(kind, owner_id) from exc
    await get_audit_service().record_archive(
        event_type="platform.crop_image_removed",
        actor_user_id=context.user_id,
        subject_kind="crop" if kind == "crops" else "crop_variety",
        subject_id=owner_id,
        details={"previous_key": previous},
    )
    return {"crop_image_url": None, "crop_icon_url": None}


# ---- Crops ------------------------------------------------------------------


@router.post(
    "/api/v1/admin/crops/{crop_id}/image/upload-init",
    response_model=CropImageUploadInitResponse,
    summary="Start a crop image upload: returns a presigned PUT.",
)
async def init_crop_image(
    crop_id: UUID,
    payload: CropImageUploadInitRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropImagesService = Depends(_service),
) -> dict[str, Any]:
    del context
    return await _init("crops", crop_id, payload, service)


@router.post(
    "/api/v1/admin/crops/{crop_id}/image/finalize",
    response_model=CropImageResponse,
    summary="Use an uploaded image as the crop's image.",
)
async def finalize_crop_image(
    crop_id: UUID,
    payload: CropImageFinalizeRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropImagesService = Depends(_service),
) -> dict[str, Any]:
    return await _finalize("crops", crop_id, payload, context, service)


@router.delete(
    "/api/v1/admin/crops/{crop_id}/image",
    response_model=CropImageResponse,
    summary="Clear the crop's image.",
)
async def remove_crop_image(
    crop_id: UUID,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropImagesService = Depends(_service),
) -> dict[str, Any]:
    return await _remove("crops", crop_id, context, service)


# ---- Varieties --------------------------------------------------------------


@router.post(
    "/api/v1/admin/crop-varieties/{variety_id}/image/upload-init",
    response_model=CropImageUploadInitResponse,
    summary="Start a variety image upload (overrides the crop's image).",
)
async def init_variety_image(
    variety_id: UUID,
    payload: CropImageUploadInitRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropImagesService = Depends(_service),
) -> dict[str, Any]:
    del context
    return await _init("varieties", variety_id, payload, service)


@router.post(
    "/api/v1/admin/crop-varieties/{variety_id}/image/finalize",
    response_model=CropImageResponse,
    summary="Use an uploaded image as the variety's own image.",
)
async def finalize_variety_image(
    variety_id: UUID,
    payload: CropImageFinalizeRequest,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropImagesService = Depends(_service),
) -> dict[str, Any]:
    return await _finalize("varieties", variety_id, payload, context, service)


@router.delete(
    "/api/v1/admin/crop-varieties/{variety_id}/image",
    response_model=CropImageResponse,
    summary="Clear the variety's own image (it shows the crop's again).",
)
async def remove_variety_image(
    variety_id: UUID,
    context: RequestContext = Depends(requires_capability(_WRITE)),
    service: CropImagesService = Depends(_service),
) -> dict[str, Any]:
    return await _remove("varieties", variety_id, context, service)


# ---- Public -----------------------------------------------------------------


@router.get(
    "/api/v1/public/crop-images/{kind}/{owner_id}/{image_id}/{size}.webp",
    response_class=Response,
    summary="A crop image rendition (no auth; cached for a year).",
)
async def get_crop_image(
    kind: CropImageKind,
    owner_id: UUID,
    image_id: UUID,
    size: int,
) -> Response:
    body = await asyncio.to_thread(read_rendition, kind, owner_id, image_id, size)
    if body is None:
        # Not cached: the worker may write it a few seconds from now.
        return Response(
            status_code=status.HTTP_404_NOT_FOUND, headers={"Cache-Control": "no-store"}
        )
    return Response(content=body, media_type="image/webp", headers={"Cache-Control": _CACHE_HIT})
