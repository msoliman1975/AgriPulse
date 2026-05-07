"""Public event types for the alerts module. Versioned per
ARCHITECTURE.md § 6.1 — bumping the suffix indicates a breaking
schema change for subscribers.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class AlertOpenedV1(Event):
    event_name: ClassVar[str] = "alerts.alert_opened.v1"

    alert_id: UUID
    block_id: UUID
    rule_code: str
    severity: str
    created_at: datetime


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
