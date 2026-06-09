"""Pydantic schemas for the recommendations REST surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ActionType = Literal[
    "irrigate",
    "fertilize",
    "spray",
    "scout",
    "harvest_window",
    "prune",
    "no_action",
    "other",
]
RecommendationState = Literal["open", "applied", "dismissed", "deferred", "expired"]
Severity = Literal["info", "warning", "critical"]


ActionHorizon = Literal["immediate", "short_term", "long_term", "monitoring"]


class RecommendationActionItem(BaseModel):
    """One localized action item within a time horizon (KB P1-B)."""

    text_en: str
    text_ar: str | None = None


class RecommendationResponse(BaseModel):
    """One row from `recommendations`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    farm_id: UUID
    tree_id: UUID
    tree_code: str
    tree_version: int
    block_crop_id: UUID | None
    action_type: ActionType
    severity: Severity
    parameters: dict[str, Any]
    # 4-horizon structured guidance (KB P1-B). Keyed by ActionHorizon;
    # absent horizons are simply omitted. Empty for trees whose leaf
    # carries only the single `text_en` summary.
    actions: dict[ActionHorizon, list[RecommendationActionItem]] = Field(default_factory=dict)
    confidence: Decimal
    tree_path: list[dict[str, Any]]
    text_en: str
    text_ar: str | None
    valid_until: datetime | None
    state: RecommendationState
    applied_at: datetime | None
    applied_by: UUID | None
    dismissed_at: datetime | None
    dismissed_by: UUID | None
    dismissal_reason: str | None
    deferred_until: datetime | None
    outcome_notes: str | None
    created_at: datetime
    updated_at: datetime


class RecommendationTransitionRequest(BaseModel):
    """PATCH /api/v1/recommendations/{id} body — drives state transitions.

    Exactly one of ``apply``, ``dismiss``, ``defer_until`` may be set.
    """

    model_config = ConfigDict(extra="forbid")

    apply: bool = False
    dismiss: bool = False
    defer_until: datetime | None = None
    dismissal_reason: str | None = Field(default=None, max_length=500)
    outcome_notes: str | None = Field(default=None, max_length=2000)


class RecommendationScheduleRequest(BaseModel):
    """POST /api/v1/recommendations/{id}/schedule body.

    Spawns a board activity from this recommendation and transitions
    the rec to ``applied`` in one transaction. The rec's ``block_id``
    and inferred activity type are defaults the caller can override.
    """

    model_config = ConfigDict(extra="forbid")

    scheduled_date: datetime | None = None
    """If omitted, scheduled = today. Time component is ignored."""
    activity_type: (
        Literal[
            "planting",
            "fertilizing",
            "spraying",
            "pruning",
            "harvesting",
            "irrigation",
            "soil_prep",
            "observation",
        ]
        | None
    ) = None
    block_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)


class DecisionTreeResponse(BaseModel):
    """One row from `public.decision_trees` plus the current version."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    # NULL = platform-shipped business knowledge; non-NULL = the
    # caller's own tenant-authored tree (PR-A).
    tenant_id: UUID | None = None
    name_en: str
    name_ar: str | None
    description_en: str | None
    description_ar: str | None
    crop_id: UUID | None
    applicable_regions: list[str]
    is_active: bool
    current_version: int | None


class EvaluateBlockResponse(BaseModel):
    """POST /api/v1/blocks/{block_id}/recommendations:evaluate response."""

    block_id: UUID
    trees_evaluated: int
    trees_skipped_crop: int
    recommendations_opened: int


# =====================================================================
# Decision-tree authoring (PlatformAdmin)
# =====================================================================


class DecisionTreeVersionResponse(BaseModel):
    """One row from `public.decision_tree_versions`. Includes both raw
    YAML and compiled JSON so the editor can round-trip without
    re-compiling."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tree_id: UUID
    version: int
    tree_yaml: str
    tree_compiled: dict[str, Any]
    compiled_hash: str
    published_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DecisionTreeDetailResponse(BaseModel):
    """Tree metadata + all versions. Drives the editor's version-history
    panel and the diff view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    # NULL = platform-shipped; non-NULL = caller's own tenant (PR-A).
    tenant_id: UUID | None = None
    name_en: str
    name_ar: str | None
    description_en: str | None
    description_ar: str | None
    crop_id: UUID | None
    applicable_regions: list[str]
    is_active: bool
    current_version: int | None
    versions: list[DecisionTreeVersionResponse]


class DecisionTreeCreateRequest(BaseModel):
    """POST /api/v1/decision-trees — create a new tree with a first
    draft version. The compiled body comes in as `tree_compiled`; the
    server validates it via `compile_tree` (same path the YAML loader
    uses) and stores the raw author-supplied YAML alongside for the
    editor to round-trip."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    crop_code: str | None = None
    tree_yaml: str = Field(min_length=1)


class DecisionTreeVersionCreateRequest(BaseModel):
    """POST /api/v1/decision-trees/{code}/versions — append a new
    draft version to an existing tree."""

    model_config = ConfigDict(extra="forbid")

    tree_yaml: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=500)


class DecisionTreeVersionPublishResponse(BaseModel):
    """POST /api/v1/decision-trees/{code}/versions/{version}:publish."""

    code: str
    version: int
    published_at: datetime


class DecisionTreeDryRunRequest(BaseModel):
    """POST /api/v1/decision-trees/{code}:dry-run — evaluate a draft
    against a real block without writing a recommendation row."""

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    # Either evaluate the persisted version OR an unsaved YAML body
    # (so the editor can test before saving).
    version: int | None = None
    tree_yaml: str | None = None


class DecisionTreeDryRunResponse(BaseModel):
    """Result of a dry-run. Mirrors `EvaluationResult` shape."""

    matched: bool
    outcome: dict[str, Any] | None
    path: list[dict[str, Any]]
    evaluation_snapshot: dict[str, Any]
    error: str | None


# =====================================================================
# Tree parameter overrides (PR-C)
# =====================================================================


class TreeParameterDeclaration(BaseModel):
    """One declared parameter from a tree's current published version.

    The settings UI renders one form row per declaration, prefilling
    with the current override value (if any), otherwise the declared
    default.
    """

    type: str
    default: Any
    description: str | None = None
    min: float | None = None
    max: float | None = None
    values: list[Any] | None = None  # only set for enum types


class TreeParameterOverridesResponse(BaseModel):
    """GET /api/v1/decision-trees/{code}/parameter-overrides response.

    Bundles the declared shape AND the current override values so the
    UI renders from a single payload.
    """

    code: str
    tree_id: UUID
    declarations: dict[str, TreeParameterDeclaration]
    overrides: dict[str, Any]


class TreeParameterOverrideUpsertRequest(BaseModel):
    """PUT /api/v1/decision-trees/{code}/parameter-overrides/{param_name}.

    ``value`` is intentionally permissive at the schema layer; the
    service coerces against the declared type and returns 400 on
    mismatch / range violation.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any


class TreeParameterOverrideResponse(BaseModel):
    code: str
    param_name: str
    value: Any
