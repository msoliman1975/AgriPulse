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


class WaterBalanceDayResponse(BaseModel):
    """One block-day of crop water accounting.

    Carries the whole derivation, not just `balance_mm`, because the answer on
    its own is not actionable: a deficit caused by peak crop demand, by absent
    rain, and by irrigation nobody logged all look identical at the headline
    and call for different responses.
    """

    model_config = ConfigDict(from_attributes=True)

    date: date_type
    balance_mm: Decimal
    etc_mm: Decimal
    et0_mm: Decimal
    kc_used: Decimal
    #: 'phenology' | 'stage_default' | 'generic_default' — how the crop
    #: coefficient resolved. A balance built on the generic fallback deserves
    #: less confidence than one built on a per-stage catalog value.
    kc_source: str
    growth_stage: str | None
    precip_mm: Decimal
    irrigation_mm: Decimal
    #: False means no irrigation was RECORDED, not that none was applied.
    #: The UI must not present an unlogged farm as being in deficit.
    irrigation_logged: bool
