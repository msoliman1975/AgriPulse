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
]


class PlanCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/plans body."""

    model_config = ConfigDict(extra="forbid")

    season_label: str = Field(min_length=1, max_length=64)
    season_year: int = Field(ge=2020, le=2100)
    name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)


class PlanUpdateRequest(BaseModel):
    """PATCH /api/v1/plans/{plan_id} body."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    status: PlanStatus | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    season_label: str
    season_year: int
    name: str | None
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

    scheduled_date: date_type | None = None
    duration_days: int | None = Field(default=None, ge=1, le=60)
    start_time: time | None = None
    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)
    state: Literal["start", "complete", "skip"] | None = None


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    block_id: UUID
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


class CalendarResponse(BaseModel):
    """GET /api/v1/farms/{farm_id}/plans/calendar response."""

    farm_id: UUID
    activities: list[ActivityResponse]
