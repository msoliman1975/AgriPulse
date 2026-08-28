"""Billing ORM models. Live in `public` schema.

`TrialSignup` is the whole of this slice: one row per trial request, from
the marketing form to a provisioned tenant.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin

#: Every state a signup can hold. Mirrors the CHECK in migration 0056 —
#: change one and you must change the other.
SIGNUP_STATUSES: tuple[str, ...] = (
    "pending_verification",
    "awaiting_approval",
    "paused",
    "approved",
    "provisioning",
    "provisioned",
    "rejected",
    "routed_to_existing",
    "failed",
    "expired",
)

#: The states that occupy a slot — one live request per address, one per
#: company domain. Mirrors the two partial unique indexes in 0056.
LIVE_STATUSES: tuple[str, ...] = (
    "pending_verification",
    "awaiting_approval",
    "paused",
    "approved",
    "provisioning",
)

#: What the review queue shows. `paused` sits here too: it is held on
#: capacity, not closed, and an admin must be able to come back to it.
QUEUE_STATUSES: tuple[str, ...] = ("awaiting_approval", "paused")


class TrialSignup(Base, TimestampedMixin):
    __tablename__ = "trial_signups"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=UUID_V7_DEFAULT,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending_verification'")
    )

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    email_domain: Mapped[str] = mapped_column(Text, nullable=False)
    organisation: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'en'"))

    verification_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_handle: Mapped[str] = mapped_column(Text, nullable=False)

    reviewed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cap_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.tenants.id", ondelete="SET NULL"),
        nullable=True,
    )
    provisioning_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    chase_email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
