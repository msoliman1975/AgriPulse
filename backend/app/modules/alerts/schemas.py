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
    rule_code: str
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
