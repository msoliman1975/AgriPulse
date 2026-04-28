"""Tenancy ORM models. Live in `public` schema. data_model § 3."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CHAR,
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


class Tenant(Base, TimestampedMixin):
    __tablename__ = "tenants"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=UUID_V7_DEFAULT,
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tax_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str] = mapped_column(
        CHAR(2), nullable=False, server_default=text("'EG'")
    )
    default_locale: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'en'")
    )
    default_timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Africa/Cairo'")
    )
    default_currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, server_default=text("'EGP'")
    )
    default_unit_system: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'feddan'")
    )
    contact_email: Mapped[str] = mapped_column(Text, nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    branding_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'active'")
    )


class TenantSubscription(Base, TimestampedMixin):
    __tablename__ = "tenant_subscriptions"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=UUID_V7_DEFAULT,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class TenantSettings(Base, TimestampedMixin):
    __tablename__ = "tenant_settings"
    __table_args__ = {"schema": "public"}

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    cloud_cover_threshold_visualization_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("60")
    )
    cloud_cover_threshold_analysis_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20")
    )
    imagery_refresh_cadence_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("24")
    )
    alert_notification_channels: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['in_app','email']::text[]"),
    )
    webhook_endpoint_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_signing_secret_kms_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    dashboard_default_indices: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['ndvi','ndwi']::text[]"),
    )
