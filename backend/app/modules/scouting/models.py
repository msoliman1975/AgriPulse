"""Scouting ORM models. Both tables live in the per-tenant schema.

A visit is dispatch metadata only — who was asked to look at which block, why,
by when, and how it ended. The observations themselves stay in
``signal_observations`` (tenant migration 0064 deliberately adds no observation
storage), so the decision-tree feedback path is untouched and a visit links to
its captured data through ``observation_group_id``.
"""

from __future__ import annotations

from datetime import date as date_type  # noqa: F401  (kept for symmetry with plans)
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin

# Kept in lock-step with the CHECK constraints in tenant migration 0064.
ORIGINS: tuple[str, ...] = (
    "recommendation",
    "alert",
    "routine",
    "ad_hoc",
    "self_initiated",
)
STATUSES: tuple[str, ...] = (
    "queued",
    "assigned",
    "accepted",
    "in_progress",
    "completed",
    "declined",
    "cancelled",
    "expired",
)
OUTCOMES: tuple[str, ...] = ("resolved", "inconclusive", "blocked")
SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")
PRIORITIES: tuple[str, ...] = ("low", "medium", "high")
MODES: tuple[str, ...] = ("triage", "auto")


class ScoutingVisit(Base, TimestampedMixin):
    """`tenant_<id>.scouting_visits` — one dispatched look at one block."""

    __tablename__ = "scouting_visits"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=False
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE"), nullable=False
    )
    # No FK — grid cells are rebuilt on rezone, so a visit must outlive them.
    cell_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    origin: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    alert_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    schedule_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    # `ad_hoc` only, enforced by CHECK: the supervisor's own words.
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # pin_point is geometry(Point,4326); not exposed via the ORM — the
    # repository renders it as GeoJSON, mirroring signal_observations.

    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'info'"))
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'medium'"))
    due_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # NULL with assigned_to set = a routing rule did it, not a person.
    assigned_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    template_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    observation_group_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    summary_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScoutingRoutingRule(Base, TimestampedMixin):
    """`tenant_<id>.scouting_routing_rules` — triage vs auto, per scope.

    Resolved most-specific-first: block → farm → tenant-wide (both ids NULL).
    """

    __tablename__ = "scouting_routing_rules"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    farm_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("farms.id", ondelete="CASCADE"), nullable=True
    )
    block_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("blocks.id", ondelete="CASCADE"), nullable=True
    )
    origin: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_severity: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'triage'"))
    default_assignee: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    fallback_assignee: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    template_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    default_due_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
