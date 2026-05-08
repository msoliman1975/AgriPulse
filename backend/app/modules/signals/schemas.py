"""Pydantic schemas for the signals REST surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ValueKind = Literal["numeric", "categorical", "event", "boolean", "geopoint"]


class SignalDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    value_kind: ValueKind
    unit: str | None
    categorical_values: list[str] | None
    value_min: Decimal | None
    value_max: Decimal | None
    attachment_allowed: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SignalDefinitionCreateRequest(BaseModel):
    """POST /api/v1/signals/definitions."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    value_kind: ValueKind
    unit: str | None = Field(default=None, max_length=32)
    categorical_values: list[str] | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    attachment_allowed: bool = False


class SignalDefinitionUpdateRequest(BaseModel):
    """PATCH /api/v1/signals/definitions/{id} — every field optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    unit: str | None = Field(default=None, max_length=32)
    categorical_values: list[str] | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    attachment_allowed: bool | None = None
    is_active: bool | None = None


class SignalAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    signal_definition_id: UUID
    farm_id: UUID | None
    block_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SignalAssignmentCreateRequest(BaseModel):
    """POST /api/v1/signals/definitions/{id}/assignments."""

    model_config = ConfigDict(extra="forbid")

    farm_id: UUID | None = None
    block_id: UUID | None = None


class GeopointModel(BaseModel):
    """WGS84 lat/lon. Stored as PostGIS geometry(Point,4326)."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SignalObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    time: datetime
    signal_definition_id: UUID
    signal_code: str
    farm_id: UUID
    block_id: UUID | None
    value_numeric: Decimal | None
    value_categorical: str | None
    value_event: str | None
    value_boolean: bool | None
    value_geopoint: GeopointModel | None
    attachment_s3_key: str | None
    attachment_download_url: str | None
    notes: str | None
    recorded_by: UUID
    inserted_at: datetime


class SignalObservationCreateRequest(BaseModel):
    """POST /api/v1/signals/definitions/{id}/observations."""

    model_config = ConfigDict(extra="forbid")

    time: datetime | None = None
    farm_id: UUID
    block_id: UUID | None = None
    value_numeric: Decimal | None = None
    value_categorical: str | None = None
    value_event: str | None = Field(default=None, max_length=500)
    value_boolean: bool | None = None
    value_geopoint: GeopointModel | None = None
    attachment_s3_key: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class SignalAttachmentInitRequest(BaseModel):
    """POST /api/v1/signals/observations:upload-init.

    Asks for a presigned PUT URL the client can upload to. Returns
    the URL plus the deterministic `attachment_s3_key` to embed in the
    subsequent observation create.
    """

    model_config = ConfigDict(extra="forbid")

    signal_definition_id: UUID
    farm_id: UUID
    content_type: str = Field(pattern=r"^[\w.+-]+/[\w.+-]+$")
    content_length: int = Field(ge=1, le=20 * 1024 * 1024)  # 20 MB cap
    filename: str = Field(min_length=1, max_length=200)


class SignalAttachmentInitResponse(BaseModel):
    attachment_s3_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime
