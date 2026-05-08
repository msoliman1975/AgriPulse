"""Audit ORM models. Live in the per-tenant schema. data_model § 13."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Text, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base


class AuditEvent(Base):
    """Hypertable; PK is logical (time, id) — see migrations/tenant/0001."""

    __tablename__ = "audit_events"
    # No __table_args__ schema — search_path resolves it to tenant_<id>.

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    subject_kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    farm_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    client_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEventArchive(Base):
    """Platform-level audit events that outlive per-tenant schema drops.

    Lives in `public`. Lifecycle operations on tenants (suspend, purge,
    etc.) write here so the trail survives `DROP SCHEMA tenant_<id>`.
    """

    __tablename__ = "audit_events_archive"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'"))
    subject_kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class AuditDataChange(Base):
    __tablename__ = "audit_data_changes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    table_schema: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    row_pk: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
