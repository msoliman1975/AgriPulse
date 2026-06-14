"""Pydantic schemas for the plan-templates module.

E1 ships the read/response shapes + the nested authoring shapes used by
the whole-tree PUT (PR-E3). The apply request/response live in PR-E2.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.plans.schemas import ActivityType

TemplateStatus = Literal["draft", "published", "archived"]
ActivityAnchor = Literal["start", "milestone", "stage"]


class PlanTemplateMilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    day_from_start: int
    sort_order: int = 0


class PlanTemplateActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    activity_type: str
    anchor: ActivityAnchor
    milestone_id: UUID | None = None
    stage_code: str | None = None
    offset_days: int = 0
    duration_days: int = 1
    product_name: str | None = None
    dosage: str | None = None
    notes: str | None = None
    start_time: time | None = None
    sort_order: int = 0


class PlanTemplateSummary(BaseModel):
    """List-row shape (no nested children)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    crop_path: str
    crop_id: UUID | None = None
    country: str | None = None
    region: str | None = None
    description: str | None = None
    status: TemplateStatus
    created_at: datetime
    updated_at: datetime


class PlanTemplateDetail(PlanTemplateSummary):
    """Full tree: header + milestones + activities."""

    milestones: list[PlanTemplateMilestoneResponse] = Field(default_factory=list)
    activities: list[PlanTemplateActivityResponse] = Field(default_factory=list)


# ---- Authoring (whole-tree write; used by PR-E3) ---------------------------


class PlanTemplateMilestoneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    day_from_start: int = Field(ge=0)
    sort_order: int = 0


class PlanTemplateActivityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_type: ActivityType
    anchor: ActivityAnchor = "start"
    # For milestone-anchored activities, the milestone's *code* (resolved to
    # an id on write). For stage-anchored, stage_code.
    milestone_code: str | None = None
    stage_code: str | None = None
    offset_days: int = 0
    duration_days: int = Field(default=1, ge=1)
    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    start_time: time | None = None
    sort_order: int = 0


class PlanTemplateWriteRequest(BaseModel):
    """Whole-tree create/replace payload."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    crop_path: str = Field(min_length=1, max_length=128)
    country: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    description: str | None = None
    milestones: list[PlanTemplateMilestoneInput] = Field(default_factory=list)
    activities: list[PlanTemplateActivityInput] = Field(default_factory=list)
