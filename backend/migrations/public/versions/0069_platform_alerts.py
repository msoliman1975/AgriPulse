"""Platform-wide integration and pipeline alerts.

A stop-gap operator surface. `integrations_health.check_failure_streaks`
(PR-IH11) already alerts tenant admins, but it can only see failures that
were *recorded as failures* — a row in `v_integration_recent_attempts`
whose status is `failed`. Everything that goes wrong by going quiet is
invisible to it:

  * a Celery task that raises before it writes an attempt row,
  * a job left in `running` that never completes and so never fails,
  * a farm whose sibling farms ingested a scene while it did not,
  * a stream that simply stops producing rows.

Each of those was live in production when this table was written, and none
had raised anything anywhere. So this table is keyed on *observations the
sweep makes*, not on failure rows other code happened to leave behind.

Why `public` and not per-tenant: the audience is the platform operator, who
needs one list across every tenant. `tenant_id` is a plain UUID with **no
foreign key** into `public.tenants` on purpose — a tenant purge does
`DROP SCHEMA`, and an FK from a long-lived platform table would make that
take an ACCESS EXCLUSIVE lock platform-wide. The sweep auto-resolves alerts
whose tenant has gone away instead.

Dedup: `uq_platform_alerts_live_key` holds **one live alert per
`alert_key`**. Severity is deliberately *not* part of that key. An alert
that escalates (warning -> critical) must move the existing row rather than
open a second one next to it, or the operator sees the same problem twice
and the count double-reports. The sweep therefore UPDATEs severity in place
and bumps `last_seen_at` / `occurrences`.

Revision ID: 0069
Revises: 0068
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0069"
down_revision: str | Sequence[str] | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# What the alert is about. `thermal` is split out from `imagery` because it
# rides a different satellite with a different revisit, so it needs its own
# staleness ceiling and reads as its own stream to an operator.
_CATEGORIES = "'imagery', 'thermal', 'weather', 'index_calc', 'task'"

# How the sweep noticed. Kept separate from category so "weather is silent"
# and "weather is failing" are distinguishable without parsing the title.
_KINDS = "'stream_silent', 'peer_lag', 'failure_streak', 'task_error', 'stuck_job'"

_SEVERITIES = "'critical', 'warning'"
_STATUSES = "'open', 'acknowledged', 'resolved'"


def upgrade() -> None:
    op.create_table(
        "platform_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # --- identity -------------------------------------------------------
        # Stable across sweeps for the same underlying problem. Built by the
        # detector, e.g. "stream_silent:<tenant>:<farm>:imagery_optical".
        sa.Column("alert_key", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        # --- subject --------------------------------------------------------
        # Denormalised labels: an alert outlives the tenant or farm it names,
        # and a resolved alert list that renders bare UUIDs is unreadable.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_slug", sa.Text(), nullable=True),
        sa.Column("tenant_name", sa.Text(), nullable=True),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("farm_name", sa.Text(), nullable=True),
        # --- payload --------------------------------------------------------
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        # Whatever the detector measured: ages, thresholds, scene ids, the
        # exception string. Rendered as the expandable body on the page.
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # --- lifecycle ------------------------------------------------------
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("acknowledged_by_email", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # 'auto' when a sweep stopped seeing the problem, 'manual' when an
        # operator closed it by hand. Tells you whether it actually got fixed.
        sa.Column("resolved_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(f"category IN ({_CATEGORIES})", name="ck_platform_alerts_category"),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="ck_platform_alerts_kind"),
        sa.CheckConstraint(f"severity IN ({_SEVERITIES})", name="ck_platform_alerts_severity"),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_platform_alerts_status"),
        schema="public",
    )

    # One live alert per key. See the module docstring for why severity is
    # excluded: escalation must move this row, not open a second one.
    op.create_index(
        "uq_platform_alerts_live_key",
        "platform_alerts",
        ["alert_key"],
        unique=True,
        postgresql_where=sa.text("status <> 'resolved'"),
        schema="public",
    )
    # The list page's default read: live alerts, worst and freshest first.
    op.create_index(
        "ix_platform_alerts_live",
        "platform_alerts",
        ["status", "severity", sa.text("last_seen_at DESC")],
        schema="public",
    )
    op.create_index(
        "ix_platform_alerts_tenant",
        "platform_alerts",
        ["tenant_id", "status"],
        schema="public",
    )


def downgrade() -> None:
    op.drop_index("ix_platform_alerts_tenant", table_name="platform_alerts", schema="public")
    op.drop_index("ix_platform_alerts_live", table_name="platform_alerts", schema="public")
    op.drop_index("uq_platform_alerts_live_key", table_name="platform_alerts", schema="public")
    op.drop_table("platform_alerts", schema="public")
