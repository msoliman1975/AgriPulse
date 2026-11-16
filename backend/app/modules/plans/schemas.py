"""Pydantic schemas for the plans REST surface."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PlanStatus = Literal["draft", "active", "completed", "archived"]
ActivityStatus = Literal["scheduled", "in_progress", "completed", "skipped"]
ActivityType = Literal[
    "planting",
    "fertilizing",
    "spraying",
    "pruning",
    "harvesting",
    "irrigation",
    "soil_prep",
    "observation",
    # Extended vocabulary for scientific crop plans (pollination = date palm,
    # growth_regulator = mango PBZ, thinning = fruit/strand thinning,
    # bagging = bunch covering, hilling = potato earthing-up).
    "pollination",
    "growth_regulator",
    "thinning",
    "bagging",
    "hilling",
    # Organic Medjool (public 0099): bunch bending and red palm weevil
    # pheromone trap servicing.
    "bending",
    "trap_service",
]


class PlanCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/plans body."""

    model_config = ConfigDict(extra="forbid")

    season_label: str = Field(min_length=1, max_length=64)
    season_year: int = Field(ge=2020, le=2100)
    name: str | None = Field(default=None, max_length=255)
    # Arabic display name (tenant migration 0087). Optional; the read path
    # falls back to `name`.
    name_ar: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)


class PlanUpdateRequest(BaseModel):
    """PATCH /api/v1/plans/{plan_id} body."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    status: PlanStatus | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    season_label: str
    season_year: int
    name: str | None
    name_ar: str | None = None
    notes: str | None
    status: PlanStatus
    created_at: datetime
    updated_at: datetime


class ActivityCreateRequest(BaseModel):
    """POST /api/v1/plans/{plan_id}/activities body."""

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    activity_type: ActivityType
    scheduled_date: date_type
    duration_days: int = Field(default=1, ge=1, le=60)
    start_time: time | None = Field(default=None)
    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class ActivityUpdateRequest(BaseModel):
    """PATCH /api/v1/activities/{activity_id} body for metadata edits.

    State transitions go through the dedicated `state` field — exactly
    one of the editable fields below + `state` may be set at a time
    (the service does not enforce this; clients can update both in
    one call). Action verbs available via `state`: `start` (→
    in_progress), `complete` (→ completed), `skip` (→ skipped).
    """

    model_config = ConfigDict(extra="forbid")

    activity_type: ActivityType | None = None
    scheduled_date: date_type | None = None
    duration_days: int | None = Field(default=None, ge=1, le=60)
    start_time: time | None = None
    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)
    state: Literal["start", "complete", "skip"] | None = None
    # Photos uploaded through POST /activities/{id}/photos/init, attached as
    # the activity is completed (build plan 3.3). Only with state=complete.
    attachment_s3_keys: list[str] | None = Field(default=None, max_length=10)


class ActivityPhotoResponse(BaseModel):
    """A photo on an activity, for staff. ``url`` is a short-lived view link."""

    id: UUID
    url: str | None = None
    taken_at: datetime | None = None
    created_at: datetime
    created_by: UUID | None = None
    #: Decision D5: shown to investors unless staff hide it.
    hidden_from_investors: bool = False


class ActivityPhotoInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: str = Field(min_length=1, max_length=64)
    content_length: int = Field(ge=1, le=15 * 1024 * 1024)


class ActivityPhotoInitResponse(BaseModel):
    """PUT the file to ``upload_url`` with ``upload_headers``; send ``s3_key`` on complete."""

    s3_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime


class ActivityPhotoUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hidden_from_investors: bool


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID | None
    farm_id: UUID
    block_id: UUID
    recommendation_id: UUID | None
    activity_type: ActivityType
    scheduled_date: date_type
    duration_days: int
    start_time: time | None
    product_name: str | None
    dosage: str | None
    notes: str | None
    status: ActivityStatus
    completed_at: datetime | None
    completed_by: UUID | None
    created_at: datetime
    updated_at: datetime
    # Provenance (PR-E): manual | template | recommendation. When a row was
    # materialised from a stage-anchored template activity, anchored_stage_code
    # carries the phenology stage it was scheduled at.
    source: str = "manual"
    anchored_stage_code: str | None = None
    # Copied from the operation manual (tenant 0101); null on manual rows.
    title: str | None = None
    title_ar: str | None = None
    # Arabic notes copied from the manual (tenant 0108, D26).
    notes_ar: str | None = None
    # Agri Operation saved plan the row came from, and whether its date was
    # moved away from the plan's default (tenant 0102).
    allocation_id: UUID | None = None
    date_overridden: bool = False
    # Field photos (tenant 0110), oldest first.
    photos: list[ActivityPhotoResponse] = Field(default_factory=list)


class CalendarResponse(BaseModel):
    """GET /api/v1/farms/{farm_id}/plans/calendar response."""

    farm_id: UUID
    activities: list[ActivityResponse]


# ---------- Board (PR-3) ---------------------------------------------------


class FlatActivityCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/activities body.

    Board-flow creation — no enclosing vegetation_plan required.
    """

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    activity_type: ActivityType
    scheduled_date: date_type
    duration_days: int = Field(default=1, ge=1, le=60)
    start_time: time | None = Field(default=None)
    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class BulkActivityCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/activities/bulk body.

    ``cells`` is the list of (block_id, scheduled_date) pairs the
    user shift-clicked. Each pair becomes one activity row.
    ``skip_existing`` lets the server de-dupe against existing
    (block, date, type) triples — useful when the user re-runs a
    bulk-add and doesn't want duplicates.
    """

    model_config = ConfigDict(extra="forbid")

    cells: list[BulkCell] = Field(min_length=1, max_length=200)
    activity_type: ActivityType
    duration_days: int = Field(default=1, ge=1, le=60)
    start_time: time | None = None
    notes: str | None = Field(default=None, max_length=4000)
    skip_existing: bool = True


class BulkCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: UUID
    scheduled_date: date_type


class BulkActivityCreateResponse(BaseModel):
    created: list[ActivityResponse]
    skipped: list[dict[str, str]]


class BoardBlockResponse(BaseModel):
    id: UUID
    code: str
    name: str | None
    name_ar: str | None = None
    unit_type: str
    # The image of the crop the block grows today, variety override first.
    crop_image_url: str | None = None
    crop_icon_url: str | None = None


class BoardResourceChip(BaseModel):
    id: UUID
    kind: Literal["worker", "equipment"]
    name: str
    name_ar: str | None = None
    role: str | None = None
    equipment_type: str | None = None


class BoardActivityResponse(ActivityResponse):
    """Same as ActivityResponse but with attached resources rolled up."""

    resources: list[BoardResourceChip] = Field(default_factory=list)


class BoardResponse(BaseModel):
    """GET /api/v1/farms/{farm_id}/board response."""

    farm_id: UUID
    week_start: date_type
    weeks: int
    blocks: list[BoardBlockResponse]
    activities: list[BoardActivityResponse]


# Resolve forward-ref between BulkActivityCreateRequest and BulkCell.
BulkActivityCreateRequest.model_rebuild()
