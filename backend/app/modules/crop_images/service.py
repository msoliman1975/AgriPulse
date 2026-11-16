"""Crop image service (build plan 3.1).

A platform admin uploads straight to S3 through a presigned PUT, then
finalizes: the API checks the object is there, small enough and of an
accepted type, points the crop (or variety) at it and asks the light worker
for renditions. Each upload has its own key, so the previous image's objects
stay where they are and any URL already cached keeps working.

Public surface: `CropImagesService`, its errors, `read_rendition`.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crop_images.repository import CropImagesRepository
from app.shared.db.ids import uuid7
from app.shared.storage import (
    IMAGE_CONTENT_TYPES,
    MAX_IMAGE_BYTES,
    RENDITION_SIZES,
    CropImageKind,
    StorageClient,
    StorageObjectMissingError,
    build_crop_image_key,
    crop_image_urls,
    get_storage_client,
    parse_crop_image_key,
    rendition_key_for,
)

#: How long the presigned PUT stays valid.
UPLOAD_EXPIRES_SECONDS = 600


class CropImageOwnerNotFoundError(Exception):
    pass


class CropImageRejectedError(Exception):
    """Wrong type, too large, not uploaded, or a key that is not this owner's."""


class Repository(Protocol):
    async def get_owner(self, kind: CropImageKind, owner_id: UUID) -> dict[str, Any] | None: ...
    async def set_key(self, kind: CropImageKind, owner_id: UUID, key: str | None) -> None: ...


class CropImagesService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        repository: Repository | None = None,
        storage: StorageClient | None = None,
    ) -> None:
        if repository is None:
            if session is None:
                raise TypeError("pass a session or a repository")
            repository = CropImagesRepository(session)
        self._repo = repository
        self._storage_override = storage

    @property
    def _storage(self) -> StorageClient:
        return self._storage_override or get_storage_client()

    async def _owner(self, kind: CropImageKind, owner_id: UUID) -> dict[str, Any]:
        owner = await self._repo.get_owner(kind, owner_id)
        if owner is None:
            raise CropImageOwnerNotFoundError(str(owner_id))
        return owner

    async def init_upload(
        self, kind: CropImageKind, owner_id: UUID, *, content_type: str, size_bytes: int
    ) -> dict[str, Any]:
        content_type = content_type.strip().lower()
        if content_type not in IMAGE_CONTENT_TYPES:
            raise CropImageRejectedError(
                f"{content_type!r} is not accepted; use PNG, JPEG or WebP."
            )
        if not 0 < size_bytes <= MAX_IMAGE_BYTES:
            raise CropImageRejectedError(f"The image must be 1 to {MAX_IMAGE_BYTES} bytes.")
        await self._owner(kind, owner_id)
        key = build_crop_image_key(
            kind=kind, owner_id=owner_id, image_id=uuid7(), content_type=content_type
        )
        presigned = self._storage.presign_upload(
            key=key,
            content_type=content_type,
            content_length=size_bytes,
            expires_seconds=UPLOAD_EXPIRES_SECONDS,
        )
        return {
            "s3_key": key,
            "upload_url": presigned.url,
            "upload_headers": presigned.headers,
            "expires_at": presigned.expires_at,
        }

    async def finalize(self, kind: CropImageKind, owner_id: UUID, s3_key: str) -> dict[str, Any]:
        """Point the owner at an uploaded original. Returns the new URLs and the old key."""
        parsed = parse_crop_image_key(s3_key)
        if parsed is None or parsed[0] != kind or parsed[1] != owner_id:
            raise CropImageRejectedError("That key was not issued for this image.")
        owner = await self._owner(kind, owner_id)
        try:
            head = self._storage.head_object(key=s3_key)
        except StorageObjectMissingError as exc:
            raise CropImageRejectedError("Nothing was uploaded to that key.") from exc
        size = int(head.get("ContentLength") or 0)
        if not 0 < size <= MAX_IMAGE_BYTES:
            raise CropImageRejectedError(f"The image must be 1 to {MAX_IMAGE_BYTES} bytes.")
        stored_type = str(head.get("ContentType") or "").lower()
        if stored_type not in IMAGE_CONTENT_TYPES:
            raise CropImageRejectedError(f"Stored type {stored_type!r} is not accepted.")
        await self._repo.set_key(kind, owner_id, s3_key)
        return {
            **crop_image_urls(s3_key),
            "previous_key": owner["image_s3_key"],
            "size_bytes": size,
            "content_type": stored_type,
        }

    async def remove(self, kind: CropImageKind, owner_id: UUID) -> str | None:
        """Clear the owner's image. Objects stay (cached URLs keep working). Returns the old key."""
        owner = await self._owner(kind, owner_id)
        await self._repo.set_key(kind, owner_id, None)
        previous: str | None = owner["image_s3_key"]
        return previous


def read_rendition(
    kind: CropImageKind,
    owner_id: UUID,
    image_id: UUID,
    size: int,
    *,
    storage: StorageClient | None = None,
) -> bytes | None:
    """A rendition's bytes, or None when the size is unknown or not written yet.

    Storage only, no database: the public route serves whatever sits under
    the crop image prefix, and the path parts are typed UUIDs, so nothing
    outside it can be named.
    """
    if size not in RENDITION_SIZES:
        return None
    key = rendition_key_for(kind=kind, owner_id=owner_id, image_id=image_id, size=size)
    try:
        return (storage or get_storage_client()).get_object(key=key)
    except StorageObjectMissingError:
        return None
