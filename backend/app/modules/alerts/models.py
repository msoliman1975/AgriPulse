"""Alerts ORM models — `Alert` lives in per-tenant schema. data_model § 11.

Stage 2 of the rules sunset removed `DefaultRule`, `RuleOverride`, and
`TenantRule`; the tables they backed (`public.default_rules`,
`tenant.rule_overrides`, `tenant.tenant_rules`) were dropped in
migrations `0025_drop_default_rules.py` + `0033_drop_tenant_rule_tables.py`.
The `Alert` model remains — both the now-retired rules engine and the
trees engine (via `recommendations.service._open_alert_from_tree`)
wrote into it. Tree-sourced alerts use a synthesised `rule_code` of
the form `tree:<tree_code>:<leaf_node_id>` so the existing partial
UNIQUE on `(block_id, rule_code) WHERE status IN open/ack/snoozed`
keeps dedup semantics intact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


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
