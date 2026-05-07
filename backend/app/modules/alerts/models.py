"""Alerts ORM models. `default_rules` lives in `public`; `rule_overrides`
and `alerts` live in the per-tenant schema (no `__table_args__["schema"]`
— search_path resolves). data_model § 11.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class DefaultRule(Base, TimestampedMixin):
    """`public.default_rules` — platform-curated rule catalog."""

    __tablename__ = "default_rules"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'warning'"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    applies_to_crop_categories: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::text[]"),
    )
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class RuleOverride(Base, TimestampedMixin):
    """`tenant_<id>.rule_overrides` — per-tenant rule customisation.

    Logical FK to `public.default_rules.code` — same pattern as
    imagery's provider_code (data_model § 5.6.1).
    """

    __tablename__ = "rule_overrides"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    modified_conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    modified_actions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    modified_severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))


class Alert(Base, TimestampedMixin):
    """`tenant_<id>.alerts` — fired alerts."""

    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'"))
    diagnosis_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnosis_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescription_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescription_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescription_activity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("plan_activities.id", ondelete="SET NULL"),
        nullable=True,
    )
    signal_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
