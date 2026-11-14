"""Crop documents service (D29).

Platform admins upload and curate; tenant users holding
`crop_document.download` see the current documents their block's crop path
inherits and open them through short-lived presigned links. Files live in
the same uploads bucket as farm and block attachments.

Public surface: `CropDocumentsService`, its errors, and `BlockCropLookup`.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crop_documents.repository import CropDocumentsRepository
from app.modules.crop_documents.schemas import (
    INLINE_TYPES,
    MAX_DOCUMENT_BYTES,
    CropDocumentFields,
    Disposition,
    content_type_for,
)
from app.shared.db.ids import uuid7
from app.shared.storage import (
    StorageClient,
    build_crop_document_key,
    content_disposition,
    get_storage_client,
)

#: How long a view or download link stays valid. Short on purpose: the link
#: is minted on the click, so it only has to outlive the browser opening it.
LINK_EXPIRES_SECONDS = 300


class CropDocumentNotFoundError(Exception):
    pass


class UnknownCropPathError(Exception):
    pass


class UnsupportedFileError(Exception):
    """The file's type is not accepted, or it is empty or too large."""


class Repository(Protocol):
    """The SQL the service needs; `CropDocumentsRepository` implements it."""

    async def crop_path_exists(self, crop_path: str) -> bool: ...
    async def get(self, document_id: UUID) -> dict[str, Any] | None: ...
    async def current_for(self, *, crop_path: str, document_code: str) -> dict[str, Any] | None: ...
    async def supersede(self, *, document_id: UUID, by: UUID, actor: UUID | None) -> None: ...
    async def insert(self, row: dict[str, Any], actor: UUID | None) -> None: ...
    async def update(
        self, document_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any] | None: ...
    async def list_for_admin(self, crop_path: str) -> list[dict[str, Any]]: ...
    async def list_current_for_path(self, crop_path: str) -> list[dict[str, Any]]: ...


class BlockCropLookup(Protocol):
    """Where a block sits and what it grows now, answered by the farms module."""

    async def farm_id_of(self, block_id: UUID) -> UUID: ...
    async def current_crop_path(self, block_id: UUID) -> str | None: ...


def _public(row: dict[str, Any]) -> dict[str, Any]:
    """The row without its storage key: callers get links, never keys."""
    return {k: v for k, v in row.items() if k != "s3_key"}


class CropDocumentsService:
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
            repository = CropDocumentsRepository(session)
        self._repo = repository
        self._storage_override = storage

    @property
    def _storage(self) -> StorageClient:
        # Resolved on use, so read-only paths never build a boto3 client.
        return self._storage_override or get_storage_client()

    # ---- Admin ----------------------------------------------------------

    async def list_for_admin(self, crop_path: str) -> list[dict[str, Any]]:
        return [_public(r) for r in await self._repo.list_for_admin(crop_path)]

    async def upload(
        self,
        fields: CropDocumentFields,
        *,
        filename: str,
        body: bytes,
        actor: UUID | None,
    ) -> dict[str, Any]:
        """Store the file and record it, superseding the current edition if any.

        Returns the new row plus `superseded_id` (the edition it replaced).
        """
        content_type = content_type_for(filename)
        if content_type is None:
            raise UnsupportedFileError(
                f"{filename!r} is not an accepted type (pdf, doc, docx, xls, xlsx, "
                "ppt, pptx, txt, md, csv)."
            )
        if not body:
            raise UnsupportedFileError("The file is empty.")
        if len(body) > MAX_DOCUMENT_BYTES:
            raise UnsupportedFileError(
                f"The file is {len(body)} bytes; the limit is {MAX_DOCUMENT_BYTES}."
            )
        if not await self._repo.crop_path_exists(fields.crop_path):
            raise UnknownCropPathError(fields.crop_path)

        document_id = uuid7()
        key = build_crop_document_key(document_id=document_id, original_filename=filename)
        # The object goes first: a row must never point at a key with nothing
        # behind it. A failure after this leaves an orphan object, which costs
        # storage and nothing else.
        await asyncio.to_thread(
            self._storage.put_object, key=key, body=body, content_type=content_type
        )

        previous = await self._repo.current_for(
            crop_path=fields.crop_path, document_code=fields.document_code
        )
        if previous is not None:
            # Before the insert: the partial unique index allows one current
            # row per (crop_path, document_code). The foreign key to the new
            # row is deferred to commit.
            await self._repo.supersede(document_id=previous["id"], by=document_id, actor=actor)
        await self._repo.insert(
            {
                "id": document_id,
                **fields.model_dump(),
                "s3_key": key,
                "original_filename": filename,
                "content_type": content_type,
                "size_bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
            actor,
        )
        created = await self._repo.get(document_id)
        assert created is not None  # just inserted in this transaction
        return {**_public(created), "superseded_id": previous["id"] if previous else None}

    async def update(
        self, document_id: UUID, fields: dict[str, Any], actor: UUID | None
    ) -> dict[str, Any]:
        updated = await self._repo.update(document_id, fields, actor)
        if updated is None:
            raise CropDocumentNotFoundError(str(document_id))
        return _public(updated)

    async def admin_link(self, document_id: UUID, disposition: Disposition) -> dict[str, Any]:
        row = await self._repo.get(document_id)
        if row is None:
            raise CropDocumentNotFoundError(str(document_id))
        return self._link(row, disposition)

    # ---- Tenant ---------------------------------------------------------

    async def for_block(self, block_id: UUID, lookup: BlockCropLookup) -> dict[str, Any]:
        crop_path = await lookup.current_crop_path(block_id)
        documents = await self._repo.list_current_for_path(crop_path) if crop_path else []
        return {
            "block_id": block_id,
            "crop_path": crop_path,
            "documents": [_public(r) for r in documents],
        }

    async def block_link(
        self,
        block_id: UUID,
        document_id: UUID,
        disposition: Disposition,
        lookup: BlockCropLookup,
    ) -> dict[str, Any]:
        """A link to a document this block shows, and only to one it shows.

        A superseded, retired or unrelated document answers not-found, so the
        block route cannot be used to fetch any file by id.
        """
        crop_path = await lookup.current_crop_path(block_id)
        if crop_path:
            for row in await self._repo.list_current_for_path(crop_path):
                if row["id"] == document_id:
                    return self._link(row, disposition)
        raise CropDocumentNotFoundError(str(document_id))

    # ---- Internal -------------------------------------------------------

    def _link(self, row: dict[str, Any], disposition: Disposition) -> dict[str, Any]:
        # A type the browser cannot render is downloaded even when viewed.
        effective: Disposition = (
            "inline"
            if disposition == "inline" and row["content_type"] in INLINE_TYPES
            else "attachment"
        )
        presigned = self._storage.presign_download(
            key=row["s3_key"],
            expires_seconds=LINK_EXPIRES_SECONDS,
            response_content_disposition=content_disposition(
                row["original_filename"], inline=effective == "inline"
            ),
            response_content_type=row["content_type"],
        )
        return {
            "url": presigned.url,
            "expires_at": presigned.expires_at,
            "disposition": effective,
        }
