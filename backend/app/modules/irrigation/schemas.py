"""Pydantic schemas for the irrigation REST surface."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ScheduleStatus = Literal["pending", "applied", "skipped"]


class IrrigationScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    scheduled_for: date_type
    recommended_mm: Decimal
    kc_used: Decimal | None
    et0_mm_used: Decimal | None
    recent_precip_mm: Decimal | None
    growth_stage_context: str | None
    soil_moisture_pct: Decimal | None
    status: ScheduleStatus
    applied_at: datetime | None
    applied_by: UUID | None
    applied_volume_mm: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class IrrigationGenerateRequest(BaseModel):
    """POST /api/v1/blocks/{block_id}/irrigation/generate body — admin/debug."""

    model_config = ConfigDict(extra="forbid")

    scheduled_for: date_type | None = Field(
        default=None,
        description=(
            "Target date for the recommendation. Defaults to today in UTC; "
            "the engine doesn't use timezone-aware bucketing for the "
            "schedule date itself (the inputs are already daily totals)."
        ),
    )


class IrrigationApplyRequest(BaseModel):
    """PATCH /api/v1/irrigation/{schedule_id} body — apply or skip."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["apply", "skip"]
    applied_volume_mm: Decimal | None = Field(
        default=None,
        ge=0,
        description=(
            "Volume actually delivered (mm). Required when action='apply'; "
            "may differ from `recommended_mm` due to operator judgment / "
            "system constraints."
        ),
    )
    notes: str | None = Field(default=None, max_length=2000)
