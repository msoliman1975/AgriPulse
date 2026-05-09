"""SQLAlchemy ORM models for the resolver tables.

Most callers should go through `SettingsResolver` rather than reading
these tables directly. The models are exposed for the rare admin path
that needs to mutate a row (PR-Set5 + Set4).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _Base(DeclarativeBase):
    pass


class PlatformDefault(_Base):
    __tablename__ = "platform_defaults"
    __table_args__ = {"schema": "public"}

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    value_schema: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )


class TenantSettingsOverride(_Base):
    __tablename__ = "tenant_settings_overrides"
    __table_args__ = {"schema": "public"}

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("public.platform_defaults.key", ondelete="RESTRICT"),
        primary_key=True,
    )
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
