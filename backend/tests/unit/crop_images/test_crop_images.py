"""Crop images (investor app v2, build plan 3.1): keys, URLs, renditions, service."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image

from app.modules.crop_images.renditions import (
    InvalidImageError,
    make_renditions,
    square_webp,
)
from app.modules.crop_images.service import (
    CropImageOwnerNotFoundError,
    CropImageRejectedError,
    CropImagesService,
    read_rendition,
)
from app.shared.storage import (
    PresignedUpload,
    StorageObjectMissingError,
    build_crop_image_key,
    crop_image_url,
    crop_image_urls,
    parse_crop_image_key,
    rendition_key,
)

CROP = UUID("01900000-0000-7000-8000-000000000001")
VARIETY = UUID("01900000-0000-7000-8000-000000000002")
IMG_A = UUID("01900000-0000-7000-8000-00000000000a")
IMG_B = UUID("01900000-0000-7000-8000-00000000000b")


def _png(width: int = 300, height: int = 200, color: str = "green") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


# ---- keys and URLs ----------------------------------------------------------


def test_key_round_trips() -> None:
    key = build_crop_image_key(
        kind="crops", owner_id=CROP, image_id=IMG_A, content_type="image/jpeg"
    )
    assert key == f"platform/crop-images/crops/{CROP}/{IMG_A}/original.jpg"
    assert parse_crop_image_key(key) == ("crops", CROP, IMG_A)
    assert rendition_key(key, 64) == f"platform/crop-images/crops/{CROP}/{IMG_A}/64.webp"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "tenants/x/blocks/y/attachments/z/a.png",
        f"platform/crop-images/strains/{CROP}/{IMG_A}/original.png",
        f"platform/crop-images/crops/{CROP}/{IMG_A}/original.gif",
        f"platform/crop-images/crops/{CROP}/../{IMG_A}/original.png",
    ],
)
def test_foreign_keys_do_not_parse(key: str) -> None:
    assert parse_crop_image_key(key) is None
    assert crop_image_url(key, 256) is None


def test_url_points_at_the_public_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "api_public_base_url", "https://api.example.test/")
    key = f"platform/crop-images/crops/{CROP}/{IMG_A}/original.png"
    assert crop_image_url(key, 256) == (
        f"https://api.example.test/api/v1/public/crop-images/crops/{CROP}/{IMG_A}/256.webp"
    )


def test_variety_override_wins_then_crop() -> None:
    crop_key = f"platform/crop-images/crops/{CROP}/{IMG_A}/original.png"
    variety_key = f"platform/crop-images/varieties/{VARIETY}/{IMG_B}/original.webp"

    both = crop_image_urls(crop_key, variety_key)
    assert both["crop_image_url"] is not None
    assert both["crop_image_url"].endswith(f"/varieties/{VARIETY}/{IMG_B}/256.webp")
    assert both["crop_icon_url"] is not None
    assert both["crop_icon_url"].endswith(f"/varieties/{VARIETY}/{IMG_B}/64.webp")

    crop_only = crop_image_urls(crop_key, None)
    assert crop_only["crop_image_url"] is not None
    assert crop_only["crop_image_url"].endswith(f"/crops/{CROP}/{IMG_A}/256.webp")

    # A broken override falls back to the crop rather than to nothing.
    assert crop_image_urls(crop_key, "garbage") == crop_only
    assert crop_image_urls(None, None) == {"crop_image_url": None, "crop_icon_url": None}


# ---- renditions -------------------------------------------------------------


def test_renditions_are_square_webp_at_each_size() -> None:
    out = square_webp(_png(300, 200))
    assert sorted(out) == [64, 128, 256]
    for size, body in out.items():
        with Image.open(io.BytesIO(body)) as image:
            assert image.format == "WEBP"
            assert image.size == (size, size)


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidImageError):
        square_webp(b"not an image")


def test_huge_canvas_is_rejected_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.crop_images import renditions

    monkeypatch.setattr(renditions, "MAX_PIXELS", 100)
    with pytest.raises(InvalidImageError):
        square_webp(_png(20, 20))


class FakeStorage:
    bucket = "uploads"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def get_object(self, *, key: str) -> bytes:
        if key not in self.objects:
            raise StorageObjectMissingError(self.bucket, key)
        return self.objects[key][0]

    def head_object(self, *, key: str) -> dict[str, Any]:
        if key not in self.objects:
            raise StorageObjectMissingError(self.bucket, key)
        body, content_type = self.objects[key]
        return {"ContentLength": len(body), "ContentType": content_type}

    def presign_upload(self, **kwargs: Any) -> PresignedUpload:
        return PresignedUpload(
            url=f"https://s3.test/{kwargs['key']}",
            headers={"Content-Type": kwargs["content_type"]},
            expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )


def test_make_renditions_writes_next_to_the_original() -> None:
    storage = FakeStorage()
    original = f"platform/crop-images/crops/{CROP}/{IMG_A}/original.png"
    storage.put_object(key=original, body=_png(), content_type="image/png")

    written = make_renditions(storage, original)  # type: ignore[arg-type]

    assert written == [rendition_key(original, size) for size in (64, 128, 256)]
    assert all(storage.objects[k][1] == "image/webp" for k in written)
    assert read_rendition("crops", CROP, IMG_A, 64, storage=storage) is not None  # type: ignore[arg-type]
    assert read_rendition("crops", CROP, IMG_A, 512, storage=storage) is None  # type: ignore[arg-type]
    assert read_rendition("crops", CROP, IMG_B, 64, storage=storage) is None  # type: ignore[arg-type]


# ---- service ----------------------------------------------------------------


class FakeRepo:
    def __init__(self, owners: dict[tuple[str, UUID], str | None]) -> None:
        self.owners = owners

    async def get_owner(self, kind: str, owner_id: UUID) -> dict[str, Any] | None:
        if (kind, owner_id) not in self.owners:
            return None
        return {"id": owner_id, "image_s3_key": self.owners[(kind, owner_id)]}

    async def set_key(self, kind: str, owner_id: UUID, key: str | None) -> None:
        self.owners[(kind, owner_id)] = key


def _service(
    owners: dict[tuple[str, UUID], str | None]
) -> tuple[CropImagesService, FakeRepo, FakeStorage]:
    repo, storage = FakeRepo(owners), FakeStorage()
    return CropImagesService(repository=repo, storage=storage), repo, storage  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_upload_then_finalize_points_the_crop_at_the_new_key() -> None:
    old = f"platform/crop-images/crops/{CROP}/{IMG_A}/original.png"
    service, repo, storage = _service({("crops", CROP): old})

    init = await service.init_upload("crops", CROP, content_type="IMAGE/PNG", size_bytes=1000)
    key = init["s3_key"]
    assert parse_crop_image_key(key) is not None
    assert key != old
    storage.put_object(key=key, body=_png(), content_type="image/png")

    result = await service.finalize("crops", CROP, key)

    assert repo.owners[("crops", CROP)] == key
    assert result["previous_key"] == old
    assert result["crop_image_url"].endswith("/256.webp")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "size"),
    [
        ("image/gif", 10),
        ("application/pdf", 10),
        ("image/png", 0),
        ("image/png", 5 * 1024 * 1024 + 1),
    ],
)
async def test_init_rejects_type_and_size(content_type: str, size: int) -> None:
    service, _, _ = _service({("crops", CROP): None})
    with pytest.raises(CropImageRejectedError):
        await service.init_upload("crops", CROP, content_type=content_type, size_bytes=size)


@pytest.mark.asyncio
async def test_unknown_owner_is_not_found() -> None:
    service, _, _ = _service({})
    with pytest.raises(CropImageOwnerNotFoundError):
        await service.init_upload("varieties", VARIETY, content_type="image/png", size_bytes=10)
    with pytest.raises(CropImageOwnerNotFoundError):
        await service.remove("crops", CROP)


@pytest.mark.asyncio
async def test_finalize_refuses_another_owners_key_and_missing_objects() -> None:
    service, repo, storage = _service({("crops", CROP): None, ("varieties", VARIETY): None})
    other = f"platform/crop-images/varieties/{VARIETY}/{IMG_A}/original.png"
    storage.put_object(key=other, body=_png(), content_type="image/png")

    # A variety's key cannot be finalized onto a crop.
    with pytest.raises(CropImageRejectedError):
        await service.finalize("crops", CROP, other)
    # Nothing uploaded behind the key.
    with pytest.raises(CropImageRejectedError):
        await service.finalize(
            "crops", CROP, f"platform/crop-images/crops/{CROP}/{uuid4()}/original.png"
        )
    # Uploaded with a type the init would not have signed.
    sneaky = f"platform/crop-images/crops/{CROP}/{IMG_B}/original.png"
    storage.put_object(key=sneaky, body=b"<svg/>", content_type="image/svg+xml")
    with pytest.raises(CropImageRejectedError):
        await service.finalize("crops", CROP, sneaky)
    assert repo.owners[("crops", CROP)] is None


@pytest.mark.asyncio
async def test_remove_clears_the_key_and_keeps_objects() -> None:
    key = f"platform/crop-images/varieties/{VARIETY}/{IMG_A}/original.png"
    service, repo, storage = _service({("varieties", VARIETY): key})
    storage.put_object(key=key, body=_png(), content_type="image/png")

    assert await service.remove("varieties", VARIETY) == key
    assert repo.owners[("varieties", VARIETY)] is None
    assert key in storage.objects
