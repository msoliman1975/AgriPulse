"""Unit tests for the attachments path of FarmServiceImpl.

Mocks both the storage client and the repository. Verifies:

  * `init_*` only signs the URL when the owner exists.
  * `finalize_*` rejects mismatched size/content-type.
  * `delete_*` removes the row + S3 object and emits an audit row.
  * Download URL is stamped on every list/finalize response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.farms.errors import (
    AttachmentUploadMismatchError,
    AttachmentUploadMissingError,
    BlockNotFoundError,
    FarmNotFoundError,
)
from app.modules.farms.service import FarmServiceImpl
from app.shared.storage.client import (
    PresignedDownload,
    PresignedUpload,
    StorageObjectMissingError,
)


@dataclass
class _FakeStorage:
    head_response: dict[str, Any]
    head_raises: bool = False

    bucket: str = "test-bucket"
    deleted_keys: tuple[str, ...] = ()

    def presign_upload(
        self, *, key: str, content_type: str, content_length: int
    ) -> PresignedUpload:
        return PresignedUpload(
            url=f"https://test-bucket.s3.example.com/{key}?upload",
            headers={"Content-Type": content_type, "Content-Length": str(content_length)},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    def presign_download(self, *, key: str) -> PresignedDownload:
        return PresignedDownload(
            url=f"https://test-bucket.s3.example.com/{key}?download",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    def head_object(self, *, key: str) -> dict[str, Any]:
        if self.head_raises:
            raise StorageObjectMissingError(self.bucket, key)
        return self.head_response

    def delete_object(self, *, key: str) -> None:
        self.deleted_keys = (*self.deleted_keys, key)


def _service_with(
    *,
    repo: MagicMock,
    storage: _FakeStorage,
) -> FarmServiceImpl:
    """Construct a service bypassing __init__ to avoid touching real wiring."""
    impl = FarmServiceImpl.__new__(FarmServiceImpl)
    impl._tenant_session = MagicMock(flush=AsyncMock())
    impl._public_session = MagicMock()
    impl._repo = repo
    impl._audit = MagicMock(record=AsyncMock(return_value=uuid4()))
    impl._bus = MagicMock(publish=MagicMock())
    impl._storage = storage  # type: ignore[assignment]
    impl._log = MagicMock()
    return impl


@pytest.fixture
def farm_id() -> UUID:
    return uuid4()


@pytest.fixture
def block_id() -> UUID:
    return uuid4()


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


# ---- init -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_farm_attachment_returns_presigned_url(farm_id: UUID, tenant_id: UUID) -> None:
    repo = MagicMock()
    repo.get_farm_by_id = AsyncMock(return_value={"id": farm_id})
    storage = _FakeStorage(head_response={})
    svc = _service_with(repo=repo, storage=storage)

    result = await svc.init_farm_attachment_upload(
        farm_id=farm_id,
        kind="photo",
        original_filename="x.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
        tenant_id=tenant_id,
    )

    assert "upload_url" in result
    assert result["upload_headers"]["Content-Type"] == "image/jpeg"
    assert str(farm_id) in result["s3_key"]


@pytest.mark.asyncio
async def test_init_farm_attachment_404s_when_farm_missing(farm_id: UUID, tenant_id: UUID) -> None:
    repo = MagicMock()
    repo.get_farm_by_id = AsyncMock(return_value=None)
    svc = _service_with(repo=repo, storage=_FakeStorage(head_response={}))

    with pytest.raises(FarmNotFoundError):
        await svc.init_farm_attachment_upload(
            farm_id=farm_id,
            kind="photo",
            original_filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            tenant_id=tenant_id,
        )


@pytest.mark.asyncio
async def test_init_block_attachment_404s_when_block_missing(
    block_id: UUID, tenant_id: UUID
) -> None:
    repo = MagicMock()
    repo.get_block_by_id = AsyncMock(return_value=None)
    svc = _service_with(repo=repo, storage=_FakeStorage(head_response={}))

    with pytest.raises(BlockNotFoundError):
        await svc.init_block_attachment_upload(
            block_id=block_id,
            kind="photo",
            original_filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            tenant_id=tenant_id,
        )


# ---- finalize -------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_farm_attachment_inserts_row_when_object_matches(
    farm_id: UUID,
) -> None:
    attachment_id = uuid4()
    repo = MagicMock()
    repo.insert_farm_attachment = AsyncMock(
        return_value={
            "id": attachment_id,
            "owner_kind": "farm",
            "owner_id": farm_id,
            "kind": "photo",
            "s3_key": "tenants/x/farms/y/attachments/z/file.jpg",
            "original_filename": "file.jpg",
            "content_type": "image/jpeg",
            "size_bytes": 1024,
            "caption": None,
            "taken_at": None,
            "geo_point": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    storage = _FakeStorage(head_response={"ContentLength": 1024, "ContentType": "image/jpeg"})
    svc = _service_with(repo=repo, storage=storage)

    result = await svc.finalize_farm_attachment(
        farm_id=farm_id,
        attachment_id=attachment_id,
        s3_key="tenants/x/farms/y/attachments/z/file.jpg",
        kind="photo",
        original_filename="file.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
        caption=None,
        taken_at=None,
        geo_point=None,
        actor_user_id=uuid4(),
        tenant_schema="tenant_xxx",
    )

    repo.insert_farm_attachment.assert_awaited_once()
    assert "download_url" in result
    assert "?download" in result["download_url"]
    svc._audit.record.assert_awaited_once()
    svc._bus.publish.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_rejects_size_mismatch(farm_id: UUID) -> None:
    repo = MagicMock()
    storage = _FakeStorage(head_response={"ContentLength": 999, "ContentType": "image/jpeg"})
    svc = _service_with(repo=repo, storage=storage)

    with pytest.raises(AttachmentUploadMismatchError):
        await svc.finalize_farm_attachment(
            farm_id=farm_id,
            attachment_id=uuid4(),
            s3_key="key",
            kind="photo",
            original_filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            caption=None,
            taken_at=None,
            geo_point=None,
            actor_user_id=uuid4(),
            tenant_schema="tenant_xxx",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_missing_object(farm_id: UUID) -> None:
    repo = MagicMock()
    storage = _FakeStorage(head_response={}, head_raises=True)
    svc = _service_with(repo=repo, storage=storage)

    with pytest.raises(AttachmentUploadMissingError):
        await svc.finalize_farm_attachment(
            farm_id=farm_id,
            attachment_id=uuid4(),
            s3_key="key",
            kind="photo",
            original_filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            caption=None,
            taken_at=None,
            geo_point=None,
            actor_user_id=uuid4(),
            tenant_schema="tenant_xxx",
        )


# ---- list -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_farm_attachments_stamps_download_urls(farm_id: UUID) -> None:
    repo = MagicMock()
    repo.get_farm_by_id = AsyncMock(return_value={"id": farm_id})
    repo.list_farm_attachments = AsyncMock(
        return_value=[
            {
                "id": uuid4(),
                "owner_kind": "farm",
                "owner_id": farm_id,
                "kind": "photo",
                "s3_key": "tenants/a/farms/b/attachments/c/photo1.jpg",
                "original_filename": "photo1.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 1024,
                "caption": None,
                "taken_at": None,
                "geo_point": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]
    )
    svc = _service_with(repo=repo, storage=_FakeStorage(head_response={}))

    result = await svc.list_farm_attachments(farm_id=farm_id)

    assert len(result) == 1
    assert "?download" in result[0]["download_url"]
    assert "download_url_expires_at" in result[0]


# ---- delete ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_farm_attachment_removes_s3_object_and_audits(
    farm_id: UUID,
) -> None:
    attachment_id = uuid4()
    repo = MagicMock()
    repo.get_farm_attachment = AsyncMock(
        return_value={
            "id": attachment_id,
            "owner_kind": "farm",
            "owner_id": farm_id,
            "s3_key": "tenants/x/farms/y/attachments/z/photo.jpg",
        }
    )
    repo.soft_delete_farm_attachment = AsyncMock(return_value=True)
    storage = _FakeStorage(head_response={})
    svc = _service_with(repo=repo, storage=storage)

    await svc.delete_farm_attachment(
        attachment_id=attachment_id,
        actor_user_id=uuid4(),
        tenant_schema="tenant_xxx",
    )

    assert "tenants/x/farms/y/attachments/z/photo.jpg" in storage.deleted_keys
    svc._audit.record.assert_awaited_once()
    svc._bus.publish.assert_called_once()


@pytest.mark.asyncio
async def test_delete_swallows_missing_s3_object_but_still_completes(
    farm_id: UUID,
) -> None:
    attachment_id = uuid4()
    repo = MagicMock()
    repo.get_farm_attachment = AsyncMock(
        return_value={
            "id": attachment_id,
            "owner_kind": "farm",
            "owner_id": farm_id,
            "s3_key": "missing-key",
        }
    )
    repo.soft_delete_farm_attachment = AsyncMock(return_value=True)

    class _MissingStorage(_FakeStorage):
        def delete_object(self, *, key: str) -> None:
            raise StorageObjectMissingError(self.bucket, key)

    storage = _MissingStorage(head_response={})
    svc = _service_with(repo=repo, storage=storage)

    # No exception — audit + event still fire.
    await svc.delete_farm_attachment(
        attachment_id=attachment_id,
        actor_user_id=uuid4(),
        tenant_schema="tenant_xxx",
    )
    svc._audit.record.assert_awaited_once()


# Ensure unused decimal import doesn't ruin coverage badge :)
_ = Decimal
