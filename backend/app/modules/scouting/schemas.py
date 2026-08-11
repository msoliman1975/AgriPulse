"""Pydantic contracts for the scouting API. Mirrors models.py — keep in step."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Origin = Literal["recommendation", "alert", "routine", "ad_hoc", "self_initiated"]
Status = Literal[
    "queued", "assigned", "accepted", "in_progress", "completed", "declined", "cancelled", "expired"
]
Outcome = Literal["resolved", "inconclusive", "blocked"]
Severity = Literal["info", "warning", "critical"]
Priority = Literal["low", "medium", "high"]
Mode = Literal["triage", "auto"]


class ScoutingVisitResponse(BaseModel):
    """A visit, self-contained enough to render offline.

    Reason text, thresholds and the form id all travel with the visit so the
    field app needs exactly one fetch and can render a cached visit later.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    block_id: UUID
    cell_id: UUID | None = None
    origin: Origin
    recommendation_id: UUID | None = None
    alert_id: UUID | None = None
    schedule_id: UUID | None = None
    title: str
    instruction: str | None = None
    reason_snapshot: dict[str, Any] | None = None
    # GeoJSON Point, rendered by the repository (the column is PostGIS).
    pin_point: dict[str, Any] | None = None
    severity: Severity
    priority: Priority
    due_by: datetime | None = None
    status: Status
    outcome: Outcome | None = None
    assigned_to: UUID | None = None
    assigned_by: UUID | None = None
    assigned_at: datetime | None = None
    accepted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    decline_reason: str | None = None
    template_id: UUID | None = None
    observation_group_id: UUID | None = None
    summary_note: str | None = None
    created_at: datetime
    updated_at: datetime


class VisitDispatchRequest(BaseModel):
    """Ad-hoc dispatch: a supervisor saw something and wants eyes on it.

    The only origin that carries human instructions, which is why
    `instruction` is required here and forbidden everywhere else.
    """

    block_id: UUID
    cell_id: UUID | None = None
    instruction: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    template_id: UUID | None = None
    assigned_to: UUID | None = None
    due_within_hours: int | None = Field(default=None, gt=0, le=24 * 30)
    severity: Severity = "info"
    priority: Priority = "medium"
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _pin_is_all_or_nothing(self) -> VisitDispatchRequest:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be supplied together")
        return self


class VisitSelfInitiatedRequest(BaseModel):
    """The scout was already there. Created straight into `in_progress`."""

    block_id: UUID
    cell_id: UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    template_id: UUID | None = None


class VisitAssignRequest(BaseModel):
    assignee_user_id: UUID


class VisitDeclineRequest(BaseModel):
    # Refusing work is legitimate; refusing it silently is not.
    reason: str = Field(min_length=1, max_length=1000)


class VisitSubmitRequest(BaseModel):
    """Close a visit.

    `observation_group_id` is the lead `signal_observations.id` of the group the
    client already wrote through the signals API. Keeping capture and closure as
    two calls means a failed submit never destroys observations that are already
    safely recorded.
    """

    outcome: Outcome
    summary_note: str | None = Field(default=None, max_length=4000)
    observation_group_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class RoutingRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID | None = None
    block_id: UUID | None = None
    origin: Origin | None = None
    min_severity: Severity | None = None
    mode: Mode
    default_assignee: UUID | None = None
    fallback_assignee: UUID | None = None
    template_id: UUID | None = None
    default_due_hours: int | None = None
    is_active: bool


class RoutingRuleWriteRequest(BaseModel):
    farm_id: UUID | None = None
    block_id: UUID | None = None
    origin: Origin | None = None
    min_severity: Severity | None = None
    mode: Mode = "triage"
    default_assignee: UUID | None = None
    fallback_assignee: UUID | None = None
    template_id: UUID | None = None
    default_due_hours: int | None = Field(default=None, gt=0)
    is_active: bool = True

    @model_validator(mode="after")
    def _block_implies_farm(self) -> RoutingRuleWriteRequest:
        # Mirrors the CHECK: resolution walks block → farm → tenant, so a
        # block-scoped rule that names no farm would leave a hole in the middle.
        if self.block_id is not None and self.farm_id is None:
            raise ValueError("a block-scoped rule must also name its farm")
        return self


class AssigneeResponse(BaseModel):
    """One person who can be sent on a visit.

    `email` is null for field workers: their address is synthetic and
    undeliverable, and a picker that falls back to it renders
    `+2010…@scouts…` where a name should be. `identity_kind` says which
    handle is the real one.
    """

    user_id: UUID
    membership_id: UUID
    full_name: str
    phone: str | None = None
    email: str | None = None
    identity_kind: Literal["email", "phone"]
    role: str
