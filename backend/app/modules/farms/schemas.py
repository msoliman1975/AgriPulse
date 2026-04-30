"""Pydantic request and response models for the farms module.

GeoJSON shapes are typed as plain `dict[str, Any]` plus a field-validator;
introducing a tagged union for Polygon/MultiPolygon would be more
pleasant for clients but every consumer of these endpoints already
parses GeoJSON natively, so the simple dict shape stays out of their way.

Areas come back in `m2` (canonical) **plus** the user's preferred unit
(`area_unit`, `area_value`) — RBAC dependency stamps the unit on
responses via the service layer using the JWT preference.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Codes are ASCII, alnum + dash + underscore, 1-32 chars.
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,31}$")

FarmType = Literal["commercial", "research", "contract"]
OwnershipType = Literal["owned", "leased", "partnership", "other"]
WaterSource = Literal["well", "canal", "nile", "desalinated", "rainfed", "mixed"]
FarmStatus = Literal["active", "archived"]

IrrigationSystem = Literal["drip", "micro_sprinkler", "pivot", "furrow", "flood", "surface", "none"]
IrrigationSource = Literal["well", "canal", "nile", "mixed"]
SoilTexture = Literal[
    "sandy", "sandy_loam", "loam", "clay_loam", "clay", "silty_loam", "silty_clay"
]
SalinityClass = Literal["non_saline", "slightly_saline", "moderately_saline", "strongly_saline"]
BlockStatus = Literal["active", "fallow", "abandoned", "under_preparation", "archived"]
BlockCropStatus = Literal["planned", "growing", "harvesting", "completed", "aborted"]

AttachmentKind = Literal["photo", "deed", "soil_test_report", "map", "other"]

UnitName = Literal["feddan", "acre", "hectare"]

FarmRoleName = Literal["FarmManager", "Agronomist", "FieldOperator", "Scout", "Viewer"]


# ---------- Geometry helpers ------------------------------------------------


def _validate_code(value: str) -> str:
    if not _CODE_RE.fullmatch(value):
        raise ValueError("code must match [A-Za-z0-9][A-Za-z0-9_-]{0,31}")
    return value


# ---------- Crops -----------------------------------------------------------


class CropResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name_en: str
    name_ar: str
    scientific_name: str | None
    category: str
    is_perennial: bool
    default_growing_season_days: int | None
    relevant_indices: list[str]


class CropVarietyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    crop_id: UUID
    code: str
    name_en: str
    name_ar: str | None


# ---------- Farms -----------------------------------------------------------


class FarmCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    boundary: dict[str, Any] = Field(description="GeoJSON MultiPolygon (SRID 4326).")
    elevation_m: Decimal | None = None
    governorate: str | None = None
    district: str | None = None
    nearest_city: str | None = None
    address_line: str | None = None
    farm_type: FarmType = "commercial"
    ownership_type: OwnershipType | None = None
    primary_water_source: WaterSource | None = None
    established_date: date | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class FarmUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    boundary: dict[str, Any] | None = None
    elevation_m: Decimal | None = None
    governorate: str | None = None
    district: str | None = None
    nearest_city: str | None = None
    address_line: str | None = None
    farm_type: FarmType | None = None
    ownership_type: OwnershipType | None = None
    primary_water_source: WaterSource | None = None
    established_date: date | None = None
    tags: list[str] | None = None


class FarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    centroid: dict[str, Any] = Field(description="GeoJSON Point (SRID 4326).")
    area_m2: Decimal
    area_value: Decimal
    area_unit: UnitName
    elevation_m: Decimal | None
    governorate: str | None
    district: str | None
    nearest_city: str | None
    address_line: str | None
    farm_type: FarmType
    ownership_type: OwnershipType | None
    primary_water_source: WaterSource | None
    established_date: date | None
    tags: list[str]
    status: FarmStatus
    created_at: datetime
    updated_at: datetime


class FarmDetailResponse(FarmResponse):
    boundary: dict[str, Any] = Field(description="GeoJSON MultiPolygon (SRID 4326).")


# ---------- Blocks ----------------------------------------------------------


class BlockCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str | None = Field(default=None, max_length=255)
    boundary: dict[str, Any] = Field(description="GeoJSON Polygon (SRID 4326).")
    elevation_m: Decimal | None = None
    irrigation_system: IrrigationSystem | None = None
    irrigation_source: IrrigationSource | None = None
    soil_texture: SoilTexture | None = None
    salinity_class: SalinityClass | None = None
    soil_ph: Decimal | None = Field(default=None, ge=0, le=14)
    responsible_user_id: UUID | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class BlockUpdateRequest(BaseModel):
    """Update block. Geometry edits and metadata edits use different RBAC."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    boundary: dict[str, Any] | None = None
    elevation_m: Decimal | None = None
    irrigation_system: IrrigationSystem | None = None
    irrigation_source: IrrigationSource | None = None
    soil_texture: SoilTexture | None = None
    salinity_class: SalinityClass | None = None
    soil_ph: Decimal | None = Field(default=None, ge=0, le=14)
    responsible_user_id: UUID | None = None
    notes: str | None = None
    tags: list[str] | None = None


class BlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    code: str
    name: str | None
    centroid: dict[str, Any]
    area_m2: Decimal
    area_value: Decimal
    area_unit: UnitName
    aoi_hash: str
    elevation_m: Decimal | None
    irrigation_system: IrrigationSystem | None
    irrigation_source: IrrigationSource | None
    soil_texture: SoilTexture | None
    salinity_class: SalinityClass | None
    soil_ph: Decimal | None
    responsible_user_id: UUID | None
    notes: str | None
    tags: list[str]
    status: BlockStatus
    created_at: datetime
    updated_at: datetime


class BlockDetailResponse(BlockResponse):
    boundary: dict[str, Any]


# ---------- Auto-grid -------------------------------------------------------


class AutoGridRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_size_m: int = Field(default=500, ge=10, le=5000)


class AutoGridCandidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    boundary: dict[str, Any]
    area_m2: Decimal


class AutoGridResponse(BaseModel):
    cell_size_m: int
    candidates: list[AutoGridCandidate]


# ---------- Block crops -----------------------------------------------------


class BlockCropAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop_id: UUID
    crop_variety_id: UUID | None = None
    season_label: str = Field(min_length=1, max_length=64)
    planting_date: date | None = None
    expected_harvest_start: date | None = None
    expected_harvest_end: date | None = None
    plant_density_per_ha: Decimal | None = None
    row_spacing_m: Decimal | None = None
    plant_spacing_m: Decimal | None = None
    notes: str | None = None
    make_current: bool = True


class BlockCropUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    growth_stage: str | None = None
    expected_harvest_start: date | None = None
    expected_harvest_end: date | None = None
    actual_harvest_date: date | None = None
    status: BlockCropStatus | None = None
    notes: str | None = None


class BlockCropResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    crop_id: UUID
    crop_variety_id: UUID | None
    season_label: str
    planting_date: date | None
    expected_harvest_start: date | None
    expected_harvest_end: date | None
    actual_harvest_date: date | None
    plant_density_per_ha: Decimal | None
    row_spacing_m: Decimal | None
    plant_spacing_m: Decimal | None
    growth_stage: str | None
    growth_stage_updated_at: datetime | None
    is_current: bool
    status: BlockCropStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Members ---------------------------------------------------------


class FarmMemberAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID
    role: FarmRoleName


class FarmMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    membership_id: UUID
    farm_id: UUID
    role: FarmRoleName
    granted_at: datetime
    revoked_at: datetime | None


# ---------- Attachments -----------------------------------------------------

# Cap aligned with prompt-02 § PR-C: 25 MB is enough for high-res phone
# photos and PDF documents without inviting bulk-data uploads.
ATTACHMENT_MAX_BYTES: int = 25 * 1024 * 1024


class AttachmentUploadInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AttachmentKind
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=ATTACHMENT_MAX_BYTES)


class AttachmentUploadInitResponse(BaseModel):
    """Response from `init`: client uses these fields to PUT to S3 directly."""

    attachment_id: UUID
    s3_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime


class AttachmentFinalizeRequest(BaseModel):
    """Body of the post-upload finalize call.

    `attachment_id` and `s3_key` come from the init response; the client
    echoes both. The remaining fields populate the row.
    """

    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID
    s3_key: str
    kind: AttachmentKind
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=ATTACHMENT_MAX_BYTES)
    caption: str | None = Field(default=None, max_length=2000)
    taken_at: datetime | None = None
    geo_point: dict[str, Any] | None = Field(default=None, description="GeoJSON Point (SRID 4326).")

    @field_validator("geo_point")
    @classmethod
    def _validate_point(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if value.get("type") != "Point":
            raise ValueError("geo_point must be a GeoJSON Point")
        coords = value.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("geo_point.coordinates must be [lon, lat]")
        return value


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_kind: Literal["farm", "block"]
    owner_id: UUID
    kind: AttachmentKind
    s3_key: str
    original_filename: str
    content_type: str
    size_bytes: int
    caption: str | None
    taken_at: datetime | None
    geo_point: dict[str, Any] | None
    download_url: str
    download_url_expires_at: datetime
    created_at: datetime
    updated_at: datetime
