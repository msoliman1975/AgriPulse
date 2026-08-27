"""Request and response bodies for field flags."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["info", "warning", "critical"]
Status = Literal["open", "closed"]
CloseReason = Literal["actioned", "no_action_needed", "duplicate"]
CommentKind = Literal["comment", "close", "reopen"]


class Geopoint(BaseModel):
    """WGS84. Field names match the signals module's `GeopointModel` exactly,
    so a client that already sends a position does not learn a second shape."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class FlagPhotoResponse(BaseModel):
    id: UUID
    attachment_s3_key: str
    # Presigned GET, minted per read. Null when the object has gone missing.
    download_url: str | None = None
    created_at: datetime


class FlagCommentResponse(BaseModel):
    id: UUID
    body: str
    author_id: UUID
    author_name: str | None = None
    author_name_ar: str | None = None
    kind: CommentKind
    created_at: datetime


class FieldFlagResponse(BaseModel):
    """One flag, with enough on it to draw a pin and open a thread."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    block_id: UUID
    block_name: str | None = None
    block_name_ar: str | None = None
    note: str
    severity: Severity
    status: Status
    # GeoJSON Point, rendered by the repository. Null when the scout recorded
    # no position — the map falls back to the block, it does not drop the flag.
    point: dict[str, Any] | None = None
    accuracy_m: int | None = None
    pin_until: datetime
    # Derived, not stored: `pin_until` in the past means the pin stops drawing.
    # It does NOT mean the flag is closed, and the two must never be read as
    # the same thing.
    is_pinned: bool
    raised_by: UUID
    raised_by_name: str | None = None
    raised_by_name_ar: str | None = None
    closed_at: datetime | None = None
    closed_by: UUID | None = None
    closed_by_name: str | None = None
    closed_by_name_ar: str | None = None
    close_reason: CloseReason | None = None
    comment_count: int = 0
    photos: list[FlagPhotoResponse] = Field(default_factory=list)
    comments: list[FlagCommentResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class FlagCreateRequest(BaseModel):
    """Raise a flag. Block is required — see migration 0081."""

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    note: str = Field(min_length=1, max_length=4000)
    severity: Severity = "warning"
    point: Geopoint | None = None
    accuracy_m: int | None = Field(default=None, ge=0, le=100_000)
    # Keys already uploaded through `/field-flags:upload-init`. The rows are
    # written only once the bytes are in storage, so a flag never points at a
    # photograph that does not exist.
    attachment_s3_keys: list[str] = Field(default_factory=list, max_length=5)


class FlagCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)


class FlagCloseRequest(BaseModel):
    """Closing needs a reason AND a comment.

    A flag closed silently reads to the scout as being ignored, and that is
    how people stop flagging things. The database enforces the reason; this
    enforces the comment.
    """

    model_config = ConfigDict(extra="forbid")

    reason: CloseReason
    comment: str = Field(min_length=1, max_length=4000)


class FlagReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=4000)


class FlagAttachmentInitRequest(BaseModel):
    """Ask for a presigned PUT to upload one photo to."""

    model_config = ConfigDict(extra="forbid")

    farm_id: UUID
    content_type: str = Field(pattern=r"^[\w.+-]+/[\w.+-]+$")
    content_length: int = Field(ge=1, le=20 * 1024 * 1024)
    filename: str = Field(min_length=1, max_length=200)


class FlagAttachmentInitResponse(BaseModel):
    attachment_s3_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime
