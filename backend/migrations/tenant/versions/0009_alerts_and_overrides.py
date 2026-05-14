"""rule_overrides + alerts — tenant-side of the alerts engine.

PR-5 of FarmDM rollout. Counterpart to migration 0012 (which added
the platform-level `default_rules` catalog). Two tables here:

  * `rule_overrides` — per-tenant customisation of a default rule.
    Overrides may flip a kill-switch (`is_disabled`), bump severity,
    or replace the conditions/actions JSONB wholesale (the engine
    picks override.field if non-null, otherwise default.field).
    UNIQUE on `rule_code` so each rule has at most one active
    override per tenant.
  * `alerts` — fired alerts. The partial UNIQUE on
    `(block_id, rule_code) WHERE status IN ('open','acknowledged','snoozed')`
    keeps the engine idempotent across re-evaluations: re-firing
    a rule against a block that already has an open alert is a
    no-op until the prior alert is resolved.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- rule_overrides ------------------------------------------------
    op.create_table(
        "rule_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # Logical FK to public.default_rules.code. We don't enforce
        # FK in DB — same pattern as imagery's provider_code (see
        # data_model § 5.6.1).
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("modified_conditions", postgresql.JSONB(), nullable=True),
        sa.Column("modified_actions", postgresql.JSONB(), nullable=True),
        sa.Column("modified_severity", sa.Text(), nullable=True),
        sa.Column(
            "is_disabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_rule_overrides_severity",
        "rule_overrides",
        "modified_severity IS NULL OR modified_severity IN ('info', 'warning', 'critical')",
    )
    op.create_index(
        "uq_rule_overrides_rule_code_active",
        "rule_overrides",
        ["rule_code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # --- alerts --------------------------------------------------------
    op.create_table(
        "alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("diagnosis_en", sa.Text(), nullable=True),
        sa.Column("diagnosis_ar", sa.Text(), nullable=True),
        sa.Column("prescription_en", sa.Text(), nullable=True),
        sa.Column("prescription_ar", sa.Text(), nullable=True),
        # Snapshot of the signal values that triggered. The shape is
        # rule-specific; consumers reading old alerts get whatever the
        # engine recorded at the time, even if the rule has since
        # changed.
        sa.Column("signal_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_alerts_severity",
        "alerts",
        "severity IN ('info', 'warning', 'critical')",
    )
    op.create_check_constraint(
        "ck_alerts_status",
        "alerts",
        "status IN ('open', 'acknowledged', 'resolved', 'snoozed')",
    )
    # One open/active alert per (block, rule) at a time. Resolved alerts
    # don't count, so the same rule can fire again after the previous
    # alert is resolved.
    op.create_index(
        "uq_alerts_block_rule_open",
        "alerts",
        ["block_id", "rule_code"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged', 'snoozed')"),
    )
    op.create_index(
        "ix_alerts_status_severity",
        "alerts",
        ["status", "severity", "created_at"],
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )
    op.create_index(
        "ix_alerts_block_created",
        "alerts",
        ["block_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_block_created", table_name="alerts")
    op.drop_index("ix_alerts_status_severity", table_name="alerts")
    op.drop_index("uq_alerts_block_rule_open", table_name="alerts")
    op.drop_constraint("ck_alerts_status", "alerts", type_="check")
    op.drop_constraint("ck_alerts_severity", "alerts", type_="check")
    op.drop_table("alerts")

    op.drop_index("uq_rule_overrides_rule_code_active", table_name="rule_overrides")
    op.drop_constraint("ck_rule_overrides_severity", "rule_overrides", type_="check")
    op.drop_table("rule_overrides")
