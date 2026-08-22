"""Email delivery for platform alerts.

Two additions, both in service of "tell the operator without making them
open a page".

`platform_role_assignments.receives_alert_emails`
    Which platform admins get the mail. A boolean on the grant row rather
    than a separate recipients table: the audience is by definition the
    people who already hold a platform role, and a second table would let
    the two lists drift. Default FALSE, so turning this migration on sends
    nothing until somebody ticks a box in /platform/admins.

`platform_alerts.notified_at` / `notified_severity`
    What has already been mailed. The sweep runs every 10 minutes and
    re-detects the same problem every time, so "send on detection" without
    a marker is "send every 10 minutes forever". Recording the severity
    alongside the timestamp is what lets an alert that escalates from
    warning to critical mail a second time: the row moves in place (see
    0069 — severity is deliberately outside the live-key unique index), so
    a bare timestamp could not tell an escalation from a re-detection.

Both columns are nullable or defaulted, so this migration is safe to run
against a table that already holds live alerts.

Revision ID: 0071
Revises: 0070
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | Sequence[str] | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_role_assignments",
        sa.Column(
            "receives_alert_emails",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="public",
    )
    op.add_column(
        "platform_alerts",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.add_column(
        "platform_alerts",
        sa.Column("notified_severity", sa.Text(), nullable=True),
        schema="public",
    )
    # The notifier reads "live alerts that have not been mailed at their
    # current severity" on every sweep. Partial, because a resolved alert is
    # never a candidate and the resolved rows are what the table accumulates.
    op.create_index(
        "ix_platform_alerts_unnotified",
        "platform_alerts",
        ["notified_at"],
        unique=False,
        schema="public",
        postgresql_where=sa.text("status <> 'resolved'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_alerts_unnotified",
        table_name="platform_alerts",
        schema="public",
    )
    op.drop_column("platform_alerts", "notified_severity", schema="public")
    op.drop_column("platform_alerts", "notified_at", schema="public")
    op.drop_column("platform_role_assignments", "receives_alert_emails", schema="public")
