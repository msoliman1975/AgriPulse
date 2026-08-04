"""Telemetry ORM models. Live in `public` — see migrations/public/0049.

Mirrors migration 0049 exactly, including server defaults, so a future
`--autogenerate` run produces no spurious diff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import Base


class UsageEvent(Base):
    """One product-telemetry event.

    Hypertable on `time`; PK is logical `(time, id)` expressed as a UNIQUE
    constraint because a hypertable cannot have a PK excluding its partitioning
    column. That pair is also the `ON CONFLICT` target that makes a duplicated
    beacon a no-op.

    Every identity column here is stamped server-side from `RequestContext`.
    A client payload that supplies `user_id` / `tenant_id` / `actor_role` /
    `is_platform_staff` has those values discarded, so a tampered client can
    only ever pollute its own row.
    """

    __tablename__ = "usage_events"
    __table_args__ = {"schema": "public"}

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    # Client-generated uuid7 (idempotency key). No server default by design.
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    schema_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )

    # --- actor (server-stamped) --------------------------------------------
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_platform_staff: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # --- what happened -----------------------------------------------------
    event_name: Mapped[str] = mapped_column(Text, nullable=False)
    feature: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Route template, never a resolved path.
    route: Mapped[str | None] = mapped_column(Text, nullable=True)
    farm_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    flow: Mapped[str | None] = mapped_column(Text, nullable=True)
    step: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- outcome + timing --------------------------------------------------
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- context -----------------------------------------------------------
    correlation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    locale: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    viewport_w: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    props: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
