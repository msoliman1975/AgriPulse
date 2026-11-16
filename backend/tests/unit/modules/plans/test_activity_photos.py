"""Activity photo rules that need no database (build plan 3.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.modules.plans.photos import (
    ActivityPhotoRejectedError,
    ActivityPhotosService,
    photo_prefix,
)
from app.modules.plans.schemas import ActivityPhotoResponse, ActivityUpdateRequest
from app.shared.storage import PresignedUpload

# Fixed ids: xdist workers must collect identical parametrize ids.
TENANT = UUID("01900000-0000-7000-8000-0000000000a1")
FARM = UUID("01900000-0000-7000-8000-0000000000b2")
ACTIVITY = UUID("01900000-0000-7000-8000-0000000000c3")
OTHER = UUID("01900000-0000-7000-8000-0000000000d4")


class _Storage:
    def presign_upload(self, **kwargs: Any) -> PresignedUpload:
        return PresignedUpload(url="u", headers={}, expires_at=datetime(2030, 1, 1, tzinfo=UTC))


def _service() -> ActivityPhotosService:
    return ActivityPhotosService(AsyncMock(), storage=_Storage())  # type: ignore[arg-type]


def test_key_sits_under_the_activity_prefix() -> None:
    out = _service().init_upload(
        tenant_id=TENANT,
        farm_id=FARM,
        activity_id=ACTIVITY,
        content_type="Image/JPEG",
        content_length=10,
    )
    prefix = photo_prefix(tenant_id=TENANT, farm_id=FARM, activity_id=ACTIVITY)
    assert out["s3_key"].startswith(prefix)
    assert out["s3_key"].endswith(".jpg")


@pytest.mark.parametrize(
    ("content_type", "size"),
    [("application/pdf", 10), ("image/svg+xml", 10), ("image/png", 0), ("image/png", 16 * 2**20)],
)
def test_init_refuses_other_types_and_sizes(content_type: str, size: int) -> None:
    with pytest.raises(ActivityPhotoRejectedError):
        _service().init_upload(
            tenant_id=TENANT,
            farm_id=FARM,
            activity_id=ACTIVITY,
            content_type=content_type,
            content_length=size,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        f"tenants/{OTHER}/farms/{FARM}/activity-photos/{ACTIVITY}/a.jpg",
        f"tenants/{TENANT}/farms/{OTHER}/activity-photos/{ACTIVITY}/a.jpg",
        f"tenants/{TENANT}/farms/{FARM}/activity-photos/{OTHER}/a.jpg",
        f"tenants/{TENANT}/farms/{FARM}/activity-photos/{ACTIVITY}/x/../a.jpg",
        f"tenants/{TENANT}/farms/{FARM}/activity-photos/{ACTIVITY}/",
    ],
    ids=["other-tenant", "other-farm", "other-activity", "traversal", "no-name"],
)
async def test_attach_refuses_keys_not_issued_for_this_activity(key: str) -> None:
    service = _service()
    with pytest.raises(ActivityPhotoRejectedError):
        await service.attach(
            tenant_id=TENANT, farm_id=FARM, activity_id=ACTIVITY, keys=[key], actor_user_id=None
        )
    # Refused before any SQL ran.
    service._session.execute.assert_not_awaited()  # type: ignore[attr-defined]


def test_photo_response_never_carries_the_storage_key() -> None:
    assert "s3_key" not in ActivityPhotoResponse.model_fields
    assert set(ActivityPhotoResponse.model_fields) == {
        "id",
        "url",
        "taken_at",
        "created_at",
        "created_by",
        "hidden_from_investors",
    }


def test_update_request_caps_photos_per_call() -> None:
    with pytest.raises(ValueError, match="at most 10"):
        ActivityUpdateRequest(state="complete", attachment_s3_keys=[f"k{i}" for i in range(11)])
