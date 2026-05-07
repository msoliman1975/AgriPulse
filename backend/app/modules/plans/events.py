"""Public event types for the plans module."""

from __future__ import annotations

from datetime import date as date_type
from typing import ClassVar
from uuid import UUID

from app.shared.eventbus import Event


class VegetationPlanCreatedV1(Event):
    event_name: ClassVar[str] = "plans.plan_created.v1"

    plan_id: UUID
    farm_id: UUID
    season_label: str
    actor_user_id: UUID | None = None


class PlanActivityScheduledV1(Event):
    event_name: ClassVar[str] = "plans.activity_scheduled.v1"

    activity_id: UUID
    plan_id: UUID
    block_id: UUID
    activity_type: str
    scheduled_date: date_type
    actor_user_id: UUID | None = None


class PlanActivityCompletedV1(Event):
    event_name: ClassVar[str] = "plans.activity_completed.v1"

    activity_id: UUID
    plan_id: UUID
    block_id: UUID
    actor_user_id: UUID | None = None


class PlanActivitySkippedV1(Event):
    event_name: ClassVar[str] = "plans.activity_skipped.v1"

    activity_id: UUID
    plan_id: UUID
    block_id: UUID
    actor_user_id: UUID | None = None
