"""Pydantic schemas for the alerts REST surface — lifecycle only.

Stage 2 of the rules sunset removed every rule-related schema
(`DefaultRuleResponse`, `RuleOverrideUpsertRequest`,
`RuleOverrideResponse`, `EvaluateBlockResponse`, `TenantRule*`). What
remains drives the alert read + lifecycle endpoints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AlertSeverity = Literal["info", "warning", "critical"]
AlertStatus = Literal["open", "acknowledged", "resolved", "snoozed"]


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    # Sub-block grid cell for cell-scoped tree alerts (per-cell P2); NULL for
    # block-scoped. cell_row/cell_col give a readable zone label (list reads).
    cell_id: UUID | None = None
    cell_row: int | None = None
    cell_col: int | None = None
    rule_code: str
    # NULL for alerts opened before migration 0063 — render as unclassified.
    action_type: str | None = None
    severity: AlertSeverity
    status: AlertStatus
    diagnosis_en: str | None
    diagnosis_ar: str | None
    prescription_en: str | None
    prescription_ar: str | None
    prescription_activity_id: UUID | None
    signal_snapshot: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: UUID | None
    resolved_at: datetime | None
    resolved_by: UUID | None
    snoozed_until: datetime | None
    # Aggregation + recurrence (0079). Mirrors RecommendationResponse field for
    # field: the Action Center reads both tables through one union, so a field
    # present on one side and not the other becomes a NULL literal in that
    # query and then a silent asymmetry in the UI.
    is_group: bool = False
    member_count: int = 0
    occurrence_count: int = 1
    day_streak: int = 1
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class AlertTransitionRequest(BaseModel):
    """PATCH /api/v1/alerts/{id} body — drives state transitions.

    Exactly one of `acknowledge`, `resolve`, `snooze_until` may be set.
    The router enforces "exactly one" so the service can branch cleanly.
    """

    model_config = ConfigDict(extra="forbid")

    acknowledge: bool = False
    resolve: bool = False
    snooze_until: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
