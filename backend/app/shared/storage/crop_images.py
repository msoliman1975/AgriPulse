"""Crop image keys and the public URLs built from them (build plan 3.1).

Layout, all under ``platform/`` (crop images belong to no tenant):

    platform/crop-images/<kind>/<owner_uuid>/<image_uuid>/original.<ext>
    platform/crop-images/<kind>/<owner_uuid>/<image_uuid>/<size>.webp

``kind`` is ``crops`` or ``varieties``. Each upload gets a new
``image_uuid``, so the public URL changes when the image does and can be
cached for a year.

The URL points at the API's public route
``/api/v1/public/crop-images/<kind>/<owner>/<image>/<size>.webp``, which
streams the rendition. Crop images are not sensitive (the same picture for
every tenant), so the route needs no token and an ``<img>`` tag can load it.
"""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from app.core.settings import get_settings

CropImageKind = Literal["crops", "varieties"]

#: The square WebP renditions the worker writes, in pixels.
RENDITION_SIZES: tuple[int, ...] = (64, 128, 256)
#: What API responses call the image (256 px) and the icon (64 px).
IMAGE_SIZE = 256
ICON_SIZE = 64

#: Accepted uploads, by content type, and the extension each is stored under.
IMAGE_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_PREFIX = "platform/crop-images"
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ORIGINAL_RE = re.compile(
    rf"^{_PREFIX}/(?P<kind>crops|varieties)/(?P<owner>{_UUID})/(?P<image>{_UUID})"
    r"/original\.(?P<ext>png|jpg|webp)$"
)


def build_crop_image_key(
    *, kind: CropImageKind, owner_id: UUID, image_id: UUID, content_type: str
) -> str:
    """Key of an uploaded original. Raises ``KeyError`` for a type not accepted."""
    ext = IMAGE_CONTENT_TYPES[content_type]
    return f"{_PREFIX}/{kind}/{owner_id}/{image_id}/original.{ext}"


def parse_crop_image_key(key: str) -> tuple[CropImageKind, UUID, UUID] | None:
    """``(kind, owner_id, image_id)`` of an original's key, or None if it is not one."""
    match = _ORIGINAL_RE.match(key)
    if match is None:
        return None
    kind: CropImageKind = "crops" if match["kind"] == "crops" else "varieties"
    return kind, UUID(match["owner"]), UUID(match["image"])


def rendition_key(original_key: str, size: int) -> str:
    """Key of one rendition, next to its original."""
    folder, _, _ = original_key.rpartition("/")
    return f"{folder}/{size}.webp"


def rendition_key_for(*, kind: CropImageKind, owner_id: UUID, image_id: UUID, size: int) -> str:
    return f"{_PREFIX}/{kind}/{owner_id}/{image_id}/{size}.webp"


def crop_image_url(original_key: str | None, size: int) -> str | None:
    """Public URL of one rendition, or None when there is no (valid) image."""
    if not original_key:
        return None
    parsed = parse_crop_image_key(original_key)
    if parsed is None:
        return None
    kind, owner_id, image_id = parsed
    base = get_settings().api_public_base_url.rstrip("/")
    return f"{base}/api/v1/public/crop-images/{kind}/{owner_id}/{image_id}/{size}.webp"


def crop_image_urls(crop_key: str | None, variety_key: str | None = None) -> dict[str, str | None]:
    """``crop_image_url`` / ``crop_icon_url``: the variety's override first, then the crop's."""
    key = variety_key if parse_crop_image_key(variety_key or "") else crop_key
    return {
        "crop_image_url": crop_image_url(key, IMAGE_SIZE),
        "crop_icon_url": crop_image_url(key, ICON_SIZE),
    }
