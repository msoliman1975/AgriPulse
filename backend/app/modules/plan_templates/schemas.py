"""Pydantic schemas for the plan-templates module.

E1 ships the read/response shapes + the nested authoring shapes used by
the whole-tree PUT (PR-E3). The apply request/response live in PR-E2.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.plans.schemas import ActivityType

TemplateStatus = Literal["draft", "published", "archived"]
ActivityAnchor = Literal["start", "milestone", "stage"]
EvidenceTier = Literal["eg_fao", "eg", "generic", "manual"]
ACTIVITY_CODE_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


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
    code: str
    activity_type: str
    title: str | None = None
    title_ar: str | None = None
    anchor: ActivityAnchor
    milestone_id: UUID | None = None
    stage_code: str | None = None
    offset_days: int = 0
    duration_days: int = 1
    product_name: str | None = None
    dosage: str | None = None
    notes: str | None = None
    product_name_ar: str | None = None
    dosage_ar: str | None = None
    notes_ar: str | None = None
    evidence_tier: EvidenceTier | None = None
    source_tree_code: str | None = None
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
    revision: int = 0
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PlanTemplateDetail(PlanTemplateSummary):
    """Full tree: header + milestones + activities."""

    milestones: list[PlanTemplateMilestoneResponse] = Field(default_factory=list)
    activities: list[PlanTemplateActivityResponse] = Field(default_factory=list)


class ManualCatalogItem(PlanTemplateSummary):
    """A published operation manual in the farm catalog."""

    activity_count: int = 0


class VarietyPhenology(BaseModel):
    """Resolved phenology for one variety (or the crop's own calendar when
    ``name_en`` is null). ``stages`` carries each stage's ``advance`` rule;
    the client turns it into weeks (H5)."""

    path: str
    code: str | None = None
    name_en: str | None = None
    name_ar: str | None = None
    is_perennial: bool = False
    stages: list[dict[str, Any]] = Field(default_factory=list)


class OperationManualResponse(PlanTemplateDetail):
    """A manual as the Agri Operation views show it: the tree, the stages
    resolved for its own crop path, and the stages per variety it covers."""

    is_perennial: bool = False
    stages: list[dict[str, Any]] = Field(default_factory=list)
    varieties: list[VarietyPhenology] = Field(default_factory=list)


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

    # Stable id within the template. Omit for a new activity: one is generated
    # on save. Keep it when editing so saved plans keep pointing at it (B3).
    code: str | None = Field(default=None, pattern=ACTIVITY_CODE_PATTERN)
    activity_type: ActivityType
    title: str | None = Field(default=None, max_length=255)
    title_ar: str | None = Field(default=None, max_length=255)
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
    product_name_ar: str | None = Field(default=None, max_length=255)
    dosage_ar: str | None = Field(default=None, max_length=255)
    notes_ar: str | None = None
    evidence_tier: EvidenceTier | None = None
    source_tree_code: str | None = Field(default=None, max_length=128)
    start_time: time | None = None
    sort_order: int = 0


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
    activity_code: str | None = None
    activity_type: str
    title: str | None = None
    title_ar: str | None = None
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


# ---- Saved plans (Agri Operation allocations; PR 3) -------------------------

StartMode = Literal["same", "per_block"]
CustomAnchor = Literal["week", "stage"]
CUSTOM_KEY_PATTERN = r"^custom:[A-Za-z0-9_-]{1,64}$"


class AllocationActivityEdit(BaseModel):
    """The farm's own product, dosage and notes for a manual activity (D1).
    A field left out keeps the manual's value."""

    model_config = ConfigDict(extra="forbid")

    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    product_name_ar: str | None = Field(default=None, max_length=255)
    dosage_ar: str | None = Field(default=None, max_length=255)
    notes_ar: str | None = Field(default=None, max_length=4000)


class AllocationCustomActivity(BaseModel):
    """An activity added for this saved plan only (D2)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=CUSTOM_KEY_PATTERN)
    activity_type: ActivityType
    title: str = Field(min_length=1, max_length=255)
    title_ar: str | None = Field(default=None, max_length=255)
    anchor: CustomAnchor = "week"
    week: int | None = Field(default=None, ge=1, le=104)
    stage_code: str | None = Field(default=None, max_length=64)
    offset_days: int = Field(default=0, ge=-365, le=730)
    duration_days: int = Field(default=1, ge=1, le=60)
    product_name: str | None = Field(default=None, max_length=255)
    dosage: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)


class AllocationBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    start_date: date


class AllocationWriteRequest(BaseModel):
    """Create or replace a saved plan. Saving applies it."""

    model_config = ConfigDict(extra="forbid")

    template_id: UUID
    season_label: str = Field(min_length=1, max_length=64)
    season_year: int = Field(ge=2000, le=2100)
    start_mode: StartMode = "same"
    blocks: list[AllocationBlock] = Field(min_length=1, max_length=500)
    excluded_codes: list[str] = Field(default_factory=list, max_length=500)
    activity_edits: dict[str, AllocationActivityEdit] = Field(default_factory=dict)
    custom_activities: list[AllocationCustomActivity] = Field(default_factory=list, max_length=200)
    # {block_id: {activity_key: date}}
    date_overrides: dict[UUID, dict[str, date]] = Field(default_factory=dict)


class AllocatedActivityPreview(BaseModel):
    activity_key: str
    source: Literal["template", "custom"]
    template_activity_id: UUID | None = None
    activity_type: str
    title: str | None = None
    title_ar: str | None = None
    scheduled_date: date
    default_date: date
    date_overridden: bool = False
    duration_days: int = 1
    anchored_stage_code: str | None = None
    product_name: str | None = None
    dosage: str | None = None
    notes: str | None = None


class AllocationBlockSchedule(BaseModel):
    block_id: UUID
    block_code: str | None = None
    crop_path: str | None = None
    start_date: date
    activities: list[AllocatedActivityPreview] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class AllocationPreviewResponse(BaseModel):
    template_id: UUID
    blocks: list[AllocationBlockSchedule] = Field(default_factory=list)
    # Blocks whose crop doesn't match the manual (C3); apply refuses them.
    rejected_blocks: list[dict[str, Any]] = Field(default_factory=list)
    # Codes the plan refers to that the manual no longer has.
    missing_codes: list[str] = Field(default_factory=list)
    total_activities: int = 0


class AllocationResponse(BaseModel):
    id: UUID
    farm_id: UUID
    plan_id: UUID
    template_id: UUID
    template_code: str | None = None
    template_name: str | None = None
    template_name_ar: str | None = None
    crop_path: str | None = None
    template_revision: int = 0
    # The manual has been published again since this plan was applied (B4).
    manual_updated: bool = False
    season_label: str
    season_year: int
    start_mode: StartMode
    blocks: list[AllocationBlock] = Field(default_factory=list)
    excluded_codes: list[str] = Field(default_factory=list)
    activity_edits: dict[str, AllocationActivityEdit] = Field(default_factory=dict)
    custom_activities: list[AllocationCustomActivity] = Field(default_factory=list)
    date_overrides: dict[UUID, dict[str, date]] = Field(default_factory=dict)
    applied_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AllocationApplyResult(BaseModel):
    allocation: AllocationResponse
    activities_created: int = 0
    activities_kept: int = 0
    skipped: int = 0
