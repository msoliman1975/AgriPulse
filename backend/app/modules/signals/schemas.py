"""Pydantic schemas for the signals REST surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ValueKind = Literal["numeric", "categorical", "event", "boolean", "geopoint"]

# CS-1 D3. Non-numeric value_kinds must always use `latest` — enforced
# in the request validators, not in DB (legacy rows + clean-data
# trade-off).
Aggregation = Literal["latest", "mean", "median", "max", "min"]
NUMERIC_VALUE_KINDS: frozenset[str] = frozenset({"numeric"})

# CS-1 D2. See models.SignalObservation.location_mode docstring.
LocationMode = Literal["entity", "point_in_entity", "free_point"]


def _coerce_aggregation_for_value_kind(value_kind: str, aggregation: str | None) -> str:
    """Non-numeric kinds always use `latest`, regardless of input."""
    if value_kind not in NUMERIC_VALUE_KINDS:
        return "latest"
    return aggregation or "latest"


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
    # CS-1 D3 — defaults applied by the 0029 migration for pre-existing
    # rows, so this is always present on read.
    aggregation: Aggregation = "latest"
    aggregation_window_days: int | None = None


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
    # CS-1 D3. Service layer should call _coerce_aggregation_for_value_kind
    # before persisting so non-numeric kinds always end up as `latest`.
    aggregation: Aggregation = "latest"
    aggregation_window_days: int | None = Field(default=None, gt=0)


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
    aggregation: Aggregation | None = None
    aggregation_window_days: int | None = Field(default=None, gt=0)


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
    # CS-1 D2 + D8. `location_point` is rendered by the repository
    # (PostGIS → GeopointModel) the same way `value_geopoint` is.
    location_mode: LocationMode = "entity"
    location_point: GeopointModel | None = None
    template_observation_id: UUID | None = None


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
    # CS-1 D2. Defaults preserve the old API surface: existing clients
    # POST with no location_mode and get `entity` behavior (no point
    # captured, no ST_Within check). New clients can opt into
    # point_in_entity / free_point. `template_observation_id` is
    # always client-supplied (lead-row writes its own id post-insert).
    location_mode: LocationMode = "entity"
    location_point: GeopointModel | None = None
    template_observation_id: UUID | None = None


class SignalTemplateResponse(BaseModel):
    """CS-1 D1. A named group of N SignalDefinitions for entry UX."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SignalTemplateDefinitionMember(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signal_definition_id: UUID
    position: int = Field(ge=0)
    is_required: bool = False


class SignalTemplateCreateRequest(BaseModel):
    """POST /api/v1/signals/templates."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    # Members are required at create time so a template never lives
    # in a broken half-defined state. Positions must be unique within
    # the template; the service rejects duplicates with a 400.
    members: list[SignalTemplateDefinitionMember] = Field(min_length=1)


class SignalTemplateUpdateRequest(BaseModel):
    """PATCH /api/v1/signals/templates/{id}."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    # When provided, replaces the full member list atomically (the
    # service performs delete-then-insert in one transaction). Null =
    # leave member list unchanged.
    members: list[SignalTemplateDefinitionMember] | None = None


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
