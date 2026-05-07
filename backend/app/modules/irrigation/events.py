"""Public event types for the irrigation module."""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class IrrigationRecommendedV1(Event):
    event_name: ClassVar[str] = "irrigation.recommended.v1"

    schedule_id: UUID
    block_id: UUID
    scheduled_for: date_type
    recommended_mm: Decimal


class IrrigationAppliedV1(Event):
    event_name: ClassVar[str] = "irrigation.applied.v1"

    schedule_id: UUID
    block_id: UUID
    applied_volume_mm: Decimal
    actor_user_id: UUID | None = None


class IrrigationSkippedV1(Event):
    event_name: ClassVar[str] = "irrigation.skipped.v1"

    schedule_id: UUID
    block_id: UUID
    actor_user_id: UUID | None = None
