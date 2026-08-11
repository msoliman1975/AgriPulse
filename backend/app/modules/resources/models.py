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
    # No `farm_id`: dropped in 0071. Availability lives in `resource_farms`,
    # because one person can work several farms and a column cannot say that.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    # U-3: optional link to a public.tenant_memberships row (login member who
    # also does field work). NULL = unlinked labour. No FK — cross-schema
    # logical reference, like farm_scopes.farm_id. See migration 0044.
    membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResourceFarm(Base):
    """`tenant_<id>.resource_farms` — which farms a resource is available on.

    The many-to-many that replaced ``resources.farm_id`` (W2-A). Mirrors
    ``public.farm_scopes``: one row per (thing, place it may be used). A
    resource with no rows here is available nowhere, which is the state farm
    purge leaves behind and the reason it archives rather than deletes.
    """

    __tablename__ = "resource_farms"

    resource_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("resources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
