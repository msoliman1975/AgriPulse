"""Notifications ORM models.

* ``NotificationTemplate`` lives in `public` (platform-curated catalog).
* ``NotificationDispatch`` and ``InAppInboxItem`` live per-tenant.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class NotificationTemplate(Base, TimestampedMixin):
    """`public.notification_templates` — platform-curated rendered text."""

    __tablename__ = "notification_templates"
    __table_args__ = {"schema": "public"}

    # Composite PK is (template_code, locale, channel, version); we
    # carry an `id` UUID as well for ergonomic FK references and audit
    # logging. Pydantic schemas read by code+locale+channel+version.
    template_code: Mapped[str] = mapped_column(Text, primary_key=True)
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, server_default=text("1"))
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, server_default=UUID_V7_DEFAULT, unique=True
    )
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationDispatch(Base, TimestampedMixin):
    """`tenant_<id>.notification_dispatches` — per (event, channel, recipient).

    Idempotency: partial UNIQUE on
    ``(alert_id, channel, recipient_user_id) WHERE status IN ('pending','sent')``.
    """

    __tablename__ = "notification_dispatches"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    alert_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    recommendation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    template_code: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    recipient_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InAppInboxItem(Base, TimestampedMixin):
    """`tenant_<id>.in_app_inbox` — bell-icon data source."""

    __tablename__ = "in_app_inbox"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    alert_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    recommendation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
