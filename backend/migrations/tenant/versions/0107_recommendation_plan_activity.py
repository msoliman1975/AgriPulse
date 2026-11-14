"""A recommendation can point at the planned activity that already covers it (F1).

When the engine opens a recommendation for a block and tree, it looks for a
live activity on that block from a saved plan or template whose manual
activity names the same tree (``source_tree_code``), still scheduled or in
progress, dated within 14 days of today. When one exists, its id is stored
here and the Action Center shows the recommendation as "Already planned"
instead of as new work.

Nullable and ``ON DELETE SET NULL``: deleting the activity leaves the
recommendation standing on its own again.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0107"
down_revision: str | Sequence[str] | None = "0106"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE recommendations
            ADD COLUMN plan_activity_id uuid
                REFERENCES plan_activities(id) ON DELETE SET NULL;
        CREATE INDEX ix_recommendations_plan_activity
            ON recommendations (plan_activity_id)
            WHERE plan_activity_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_recommendations_plan_activity;
        ALTER TABLE recommendations DROP COLUMN IF EXISTS plan_activity_id;
        """
    )
