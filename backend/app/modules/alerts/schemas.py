"""Pydantic schemas for the alerts REST surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AlertSeverity = Literal["info", "warning", "critical"]
AlertStatus = Literal["open", "acknowledged", "resolved", "snoozed"]
RuleStatus = Literal["active", "draft", "retired"]


class DefaultRuleResponse(BaseModel):
    """One row from `public.default_rules`."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_ar: str | None
    description_en: str | None
    description_ar: str | None
    severity: AlertSeverity
    status: RuleStatus
    applies_to_crop_categories: list[str]
    conditions: dict[str, Any]
    actions: dict[str, Any]
    version: int


class RuleOverrideUpsertRequest(BaseModel):
    """PUT /api/v1/rules/overrides/{rule_code} body."""

    model_config = ConfigDict(extra="forbid")

    modified_conditions: dict[str, Any] | None = None
    modified_actions: dict[str, Any] | None = None
    modified_severity: AlertSeverity | None = None
    is_disabled: bool = False


class RuleOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_code: str
    modified_conditions: dict[str, Any] | None
    modified_actions: dict[str, Any] | None
    modified_severity: AlertSeverity | None
    is_disabled: bool
    created_at: datetime
    updated_at: datetime


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


class EvaluateBlockResponse(BaseModel):
    """POST /api/v1/blocks/{block_id}/alerts:evaluate response.

    Returns counts so admins can see how many alerts the on-demand
    evaluation produced. Mostly an admin/debug endpoint; the Beat
    sweep does the real work.
    """

    block_id: UUID
    alerts_opened: int
    rules_evaluated: int
    rules_skipped_disabled: int


# =====================================================================
# Tenant rule authoring
# =====================================================================


class TenantRuleResponse(BaseModel):
    """One row from `tenant_<id>.tenant_rules`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name_en: str
    name_ar: str | None
    description_en: str | None
    description_ar: str | None
    severity: AlertSeverity
    status: RuleStatus
    applies_to_crop_categories: list[str]
    conditions: dict[str, Any]
    actions: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class TenantRuleCreateRequest(BaseModel):
    """POST /api/v1/rules/tenant."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name_en: str = Field(min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    description_en: str | None = Field(default=None, max_length=2000)
    description_ar: str | None = Field(default=None, max_length=2000)
    severity: AlertSeverity = "warning"
    applies_to_crop_categories: list[str] = Field(default_factory=list)
    conditions: dict[str, Any]
    actions: dict[str, Any]


class TenantRuleUpdateRequest(BaseModel):
    """PATCH /api/v1/rules/tenant/{code} — every field optional."""

    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    description_en: str | None = Field(default=None, max_length=2000)
    description_ar: str | None = Field(default=None, max_length=2000)
    severity: AlertSeverity | None = None
    status: RuleStatus | None = None
    applies_to_crop_categories: list[str] | None = None
    conditions: dict[str, Any] | None = None
    actions: dict[str, Any] | None = None
