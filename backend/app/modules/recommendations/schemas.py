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


class DecisionTreeResponse(BaseModel):
    """One row from `public.decision_trees` plus the current version."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
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
