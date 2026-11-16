"""Wire shapes for crop image uploads."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.shared.storage import MAX_IMAGE_BYTES


class CropImageUploadInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: image/png, image/jpeg or image/webp.
    content_type: str = Field(min_length=1, max_length=64)
    size_bytes: int = Field(gt=0, le=MAX_IMAGE_BYTES)


class CropImageUploadInitResponse(BaseModel):
    """PUT the file to ``upload_url`` with ``upload_headers``, then finalize with ``s3_key``."""

    s3_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime


class CropImageFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s3_key: str = Field(min_length=1, max_length=300)


class CropImageResponse(BaseModel):
    """The owner's own image after a change. Null URLs: no image of its own."""

    crop_image_url: str | None = None
    crop_icon_url: str | None = None
