"""Public event types for the alerts module. Versioned per
ARCHITECTURE.md § 6.1 — bumping the suffix indicates a breaking
schema change for subscribers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class AlertOpenedV1(Event):
    event_name: ClassVar[str] = "alerts.alert_opened.v1"

    alert_id: UUID
    block_id: UUID
    rule_code: str
    severity: str
    created_at: datetime
    # Tenant context — added so cross-module subscribers (e.g.
    # notifications) can scope DB writes without walking every tenant.
    # Optional with default for back-compat with any payloads queued
    # before the field landed.
    tenant_schema: str | None = None
    # Alert content snapshot. Carried on the event so a sync subscriber
    # running on a different DB connection can render templates without
    # querying the not-yet-committed `alerts` row. Optional with
    # back-compat defaults.
    farm_id: UUID | None = None
    diagnosis_en: str | None = None
    diagnosis_ar: str | None = None
    prescription_en: str | None = None
    prescription_ar: str | None = None
    signal_snapshot: dict[str, Any] | None = None


class AlertAcknowledgedV1(Event):
    event_name: ClassVar[str] = "alerts.alert_acknowledged.v1"

    alert_id: UUID
    block_id: UUID
    rule_code: str
    actor_user_id: UUID | None = None


class AlertResolvedV1(Event):
    event_name: ClassVar[str] = "alerts.alert_resolved.v1"

    alert_id: UUID
    block_id: UUID
    rule_code: str
    actor_user_id: UUID | None = None
