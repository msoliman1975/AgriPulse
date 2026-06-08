"""Resources ORM models. Tenant-scoped — search_path resolves the schema.

One table, discriminated by ``kind``. Workers carry a ``role`` and
optional ``phone``; equipment carries an ``equipment_type``. The CHECK
constraint ``ck_resources_kind_fields_exclusive`` enforces the
shape — see migration 0031 for the contract.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class Resource(Base, TimestampedMixin):
    """`tenant_<id>.resources` — workers + equipment catalog per farm."""

    __tablename__ = "resources"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityResource(Base):
    """`tenant_<id>.activity_resources` — assignment join table.

    Composite PK (activity_id, resource_id). ON DELETE CASCADE on both
    FKs so deleting an activity (or hard-deleting a resource, which we
    do not normally do) cleans up assignments.
    """

    __tablename__ = "activity_resources"

    activity_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("plan_activities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    resource_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
