"""Pydantic schemas for the plan-templates module.

E1 ships the read/response shapes + the nested authoring shapes used by
the whole-tree PUT (PR-E3). The apply request/response live in PR-E2.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.plans.schemas import ActivityType

# The inputs catalogue's dose units (public 0106/0107 CHECK). Repeated here
# rather than imported: module boundaries let schemas import only another
# module's service, and the database CHECK is the shared source of truth.
DoseUnit = Literal[
    "kg/plant",
    "g/plant",
    "L/plant/week",
    "cards/plant",
    "kg/plant/year_of_age",
    "g/100 L",
    "mg/L",
    "%",
    "ppm",
    "traps/ha",
    "kg/ha",
    "L/ha",
    "other",
]

TemplateStatus = Literal["draft", "published", "archived"]
ActivityAnchor = Literal["start", "milestone", "stage"]


class PlanTemplateMilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    name_ar: str | None = None
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
    input_id: UUID | None = None
    dose_value: Decimal | None = None
    dose_value_max: Decimal | None = None
    dose_unit: DoseUnit | None = None
    notes: str | None = None
    start_time: time | None = None
    sort_order: int = 0


class PlanTemplateSummary(BaseModel):
    """List-row shape (no nested children)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    # Arabic display name (public migration 0075). Null when nobody has
    # written one; the client falls back to `name`.
    name_ar: str | None = None
    crop_path: str
    crop_id: UUID | None = None
    country: str | None = None
    region: str | None = None
    description: str | None = None
    description_ar: str | None = None
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
    name_ar: str | None = Field(default=None, max_length=255)
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
    # D20: an input from the catalogue and a structured dose. A dose needs a
    # unit and a unit needs a dose; a range needs value <= value_max.
    input_id: UUID | None = None
    dose_value: Decimal | None = Field(default=None, ge=0)
    dose_value_max: Decimal | None = Field(default=None, ge=0)
    dose_unit: DoseUnit | None = None
    notes: str | None = None
    start_time: time | None = None
    sort_order: int = 0

    @model_validator(mode="after")
    def _dose_shape(self) -> Self:
        has_amount = self.dose_value is not None or self.dose_value_max is not None
        if has_amount != (self.dose_unit is not None):
            raise ValueError("a dose needs both an amount and a unit")
        if (
            self.dose_value is not None
            and self.dose_value_max is not None
            and self.dose_value > self.dose_value_max
        ):
            raise ValueError("dose_value is above dose_value_max")
        return self


class PlanTemplateWriteRequest(BaseModel):
    """Whole-tree create/replace payload."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    crop_path: str = Field(min_length=1, max_length=128)
    country: str | None = Field(default=None, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    description: str | None = None
    description_ar: str | None = None
    milestones: list[PlanTemplateMilestoneInput] = Field(default_factory=list)
    activities: list[PlanTemplateActivityInput] = Field(default_factory=list)


# ---- Apply / preview (tenant; PR-E2) ---------------------------------------


class ApplyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    start_date: date


class PlanTemplateApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    farm_id: UUID
    season_label: str = Field(min_length=1, max_length=64)
    season_year: int = Field(ge=2000, le=2100)
    blocks: list[ApplyBlock] = Field(min_length=1)


class ResolvedActivityPreview(BaseModel):
    template_activity_id: UUID
    activity_type: str
    scheduled_date: date
    duration_days: int
    anchored_stage_code: str | None = None


class BlockSchedule(BaseModel):
    block_id: UUID
    block_code: str | None = None
    activities: list[ResolvedActivityPreview] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class PlanTemplatePreviewResponse(BaseModel):
    template_id: UUID
    blocks: list[BlockSchedule] = Field(default_factory=list)
    total_activities: int = 0
    total_skipped: int = 0


class PlanTemplateApplyResponse(BaseModel):
    template_id: UUID
    plan_id: UUID
    blocks_applied: int = 0
    activities_created: int = 0
    skipped: int = 0


class AppliableBlock(BaseModel):
    block_id: UUID
    block_code: str | None = None
    crop_path: str
    planting_date: date | None = None


class AppliableTemplate(PlanTemplateSummary):
    """A published template that matches the farm + the blocks it fits."""

    matching_blocks: list[AppliableBlock] = Field(default_factory=list)


# ---- Phenology resolution (authoring stage-picker; PR-E3) ------------------


class ResolvedPhenologyResponse(BaseModel):
    """Resolved phenology stages for a crop path — feeds the authoring UI's
    stage picker so it only offers valid stage codes."""

    crop_path: str
    is_perennial: bool = False
    stages: list[dict[str, Any]] = Field(default_factory=list)
