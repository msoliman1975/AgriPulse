"""Wire shapes for the platform alert API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

AlertCategory = Literal["imagery", "thermal", "weather", "index_calc", "task"]
AlertKind = Literal["stream_silent", "peer_lag", "failure_streak", "task_error", "stuck_job"]
AlertSeverity = Literal["critical", "warning"]
AlertStatus = Literal["open", "acknowledged", "resolved"]


class PlatformAlertRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_key: str
    category: AlertCategory
    kind: AlertKind
    severity: AlertSeverity
    status: AlertStatus

    tenant_id: UUID | None = None
    tenant_slug: str | None = None
    tenant_name: str | None = None
    farm_id: UUID | None = None
    farm_name: str | None = None

    title: str
    detail: str | None = None
    context: dict[str, Any] = {}

    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    acknowledged_by_email: str | None = None
    resolved_at: datetime | None = None
    resolved_reason: str | None = None


class PlatformAlertPage(BaseModel):
    items: list[PlatformAlertRow]
    total: int
    limit: int
    offset: int


class PlatformAlertSummary(BaseModel):
    """What the red bar reads.

    `critical` and `warning` count live alerts only (open + acknowledged);
    an acknowledged alert is still broken, so it must keep the bar up. The
    banner shows itself on `critical > 0`.
    """

    critical: int
    warning: int
    open: int
    acknowledged: int
    newest_at: datetime | None = None


class SweepResult(BaseModel):
    tenants_scanned: int
    tenants_failed: int
    findings: int
    resolved: int
    # How many alerts the digest covered and how many recipients it reached.
    # `emails_alerts` counts new or escalated alerts, so it is normally 0 on
    # a sweep that found nothing that was not already mailed.
    emails_sent: int = 0
    emails_alerts: int = 0
    swept_at: str
