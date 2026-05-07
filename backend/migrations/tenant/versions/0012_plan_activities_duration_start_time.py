"""plan_activities — add duration_days + start_time.

PR-1 of the AgriPulse UX slice. The Plan view's Gantt-style timeline
needs a real width (``duration_days``) and a real time-of-day label
(``start_time``); the original ``plan_activities`` schema only carried
a ``scheduled_date``.

Timezone convention (locked 2026-05-07 — see new-ux/IMPLEMENTATION_PLAN.md §14):
``scheduled_date`` and ``start_time`` are interpreted in the **farm's
local timezone** (``farms.timezone``, populated since Slice-2). The
columns themselves carry no zone info — that's intentional, since
naïve farm-local is what crews use day-to-day. UTC conversion happens
at render time when needed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plan_activities",
        sa.Column(
            "duration_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "plan_activities",
        sa.Column("start_time", sa.Time(), nullable=True),
    )
    op.create_check_constraint(
        "ck_plan_activities_duration_days",
        "plan_activities",
        "duration_days >= 1 AND duration_days <= 60",
    )


def downgrade() -> None:
    op.drop_constraint("ck_plan_activities_duration_days", "plan_activities", type_="check")
    op.drop_column("plan_activities", "start_time")
    op.drop_column("plan_activities", "duration_days")
