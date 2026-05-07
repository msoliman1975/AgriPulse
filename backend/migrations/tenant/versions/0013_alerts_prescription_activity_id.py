"""alerts.prescription_activity_id — link alerts to a recommended activity.

PR-1b of the AgriPulse UX slice. Lets the alerts feed's "Resolve"
button deep-link to a specific bar on the Plan view rather than just
to the lane. Nullable: not every alert prescribes an activity (info /
system alerts don't), and the engine writes ``NULL`` for now — the
column exists so the FE deep-link contract is stable and a follow-up
sweep can backfill values when the alerts engine grows a
``create_activity`` action.

ON DELETE SET NULL: deleting the activity drops the link cleanly; the
alert's prescription_en / prescription_ar text remains intact.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column(
            "prescription_activity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plan_activities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_alerts_prescription_activity_id",
        "alerts",
        ["prescription_activity_id"],
        postgresql_where=sa.text("prescription_activity_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_prescription_activity_id", table_name="alerts")
    op.drop_column("alerts", "prescription_activity_id")
