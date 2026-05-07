"""Irrigation ORM models. Tenant-scoped — search_path resolves the
schema. data_model § 13.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class IrrigationSchedule(Base, TimestampedMixin):
    """`tenant_<id>.irrigation_schedules` — one recommendation per
    (block, scheduled_for) day. Engine-driven, operator-confirmed."""

    __tablename__ = "irrigation_schedules"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_for: Mapped[date_type] = mapped_column(Date, nullable=False)
    recommended_mm: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    kc_used: Mapped[Decimal | None] = mapped_column(Numeric(5, 3), nullable=True)
    et0_mm_used: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    recent_precip_mm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    growth_stage_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    soil_moisture_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    applied_volume_mm: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
