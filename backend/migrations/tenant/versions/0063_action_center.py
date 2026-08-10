"""Action Center — the two columns the unified alerts+recommendations screen needs.

The Action Center surfaces recommendations and alerts in one queue, groups them
by task type / block / due date, and dispatches them to a named person.

**1. ``alerts.action_type``.** The engine already decides one — ``TreeOutcome``
carries ``action_type`` for every leaf regardless of whether the leaf opens a
recommendation or an alert — but the alert row throws it away and keeps only
``rule_code``. So "group this queue by task type" could order the
recommendations and not the alerts, which is the one grouping a spray operator
actually wants. Nullable, because every alert already in the table predates the
column and there is no honest way to backfill it: recovering the value means
resolving ``tree:<code>:<leaf>`` against the tree *version that fired*, which
may since have been edited. The UI shows NULL as "unclassified" rather than
guessing a verb someone might act on.

**2. ``plan_activities.assigned_membership_id``.** The board records who
*completed* an activity (``completed_by``) and has never recorded who is
expected to do it. Dispatch is exactly that statement, so the column is the
feature.

Named for memberships, not users, and deliberately so: the block already names
its responsible person as ``blocks.agronomist_membership_id`` (U-4b), and farm
members are handed out as ``membership_id`` by ``GET /farms/{id}/members``.
Assignment defaults to the block's member, so storing a *user* id here would
mean converting domains on every read and write. ``completed_by`` holds a user
id and is left alone — the distinct name is the guard against reading one as
the other.

No FK on either: tenant tables in this codebase do not point at the public
schema's identity tables.

There is no third column for "block responsible". ``agronomist_membership_id``
already is that field, already has a picker in the block form, and a parallel
``responsible_user_id`` would be a second answer to "who owns this block" that
drifts from the first in silence.

Both changes are additive and nullable, so this is safe to run ahead of the
code that writes them — which is what the PreSync hook does anyway.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0063"
down_revision: str | Sequence[str] | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("action_type", sa.Text(), nullable=True))
    op.add_column(
        "plan_activities",
        sa.Column("assigned_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # "What is on my plate" is the scout app's only query and it runs on every
    # app open. Partial — an activity with no assignee is never the answer to
    # it, and unassigned is the majority state.
    op.create_index(
        "ix_plan_activities_assigned",
        "plan_activities",
        ["assigned_membership_id", "scheduled_date"],
        unique=False,
        postgresql_where=sa.text("assigned_membership_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_plan_activities_assigned", table_name="plan_activities")
    op.drop_column("plan_activities", "assigned_membership_id")
    op.drop_column("alerts", "action_type")
