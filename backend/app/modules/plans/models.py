"""Plans ORM models. Tenant-scoped — search_path resolves the schema.
data_model § 12.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, Time, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class VegetationPlan(Base, TimestampedMixin):
    """`tenant_<id>.vegetation_plans` — one per farm per season."""

    __tablename__ = "vegetation_plans"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    season_label: Mapped[str] = mapped_column(Text, nullable=False)
    season_year: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))


class PlanActivity(Base, TimestampedMixin):
    """`tenant_<id>.plan_activities` — scheduled activity items."""

    __tablename__ = "plan_activities"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    plan_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vegetation_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="RESTRICT"),
        nullable=False,
    )
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    dosage: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'scheduled'"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
