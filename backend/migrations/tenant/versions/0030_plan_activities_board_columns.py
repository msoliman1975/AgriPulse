"""Board PR-1 — flat-activity columns on plan_activities.

Prepares plan_activities for the Weekly Operations Board model where
activities live directly on a farm + block (no enclosing seasonal plan
required) and may optionally trace back to a recommendation.

Adds three columns:

  * `farm_id`            -- denormalized from blocks.farm_id so the
                           board query can filter without an extra
                           join. Backfilled and made NOT NULL in the
                           same migration; FK with ON DELETE CASCADE.
  * `recommendation_id`  -- nullable FK to recommendations(id). Set
                           when an activity is created by "drag rec to
                           cell" (PR-5). ON DELETE SET NULL so deleting
                           a rec doesn't cascade-wipe the activity.
  * Relaxes `plan_id`    -- was NOT NULL, now nullable. New activities
                           created via the board flow leave it null;
                           legacy rows keep their plan reference.

Indexes:
  * `ix_plan_activities_farm_id_scheduled_date` powers the board view
    (farm + date-range scan).
  * `ix_plan_activities_recommendation_id` (partial, NOT NULL) speeds
    up "is this rec already scheduled?" checks.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Was briefly labelled "0030a" to coexist with a parallel
# tree_parameter_overrides migration that also claimed revision "0030".
# That sibling has since been renumbered to "0032", leaving "0030a"
# pointing at a now-missing parent. Reclaim revision "0030" with
# down_revision="0029" so the chain is contiguous again.
revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- farm_id (denormalized from blocks) ----------------------------
    op.add_column(
        "plan_activities",
        sa.Column("farm_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE plan_activities pa
        SET farm_id = b.farm_id
        FROM blocks b
        WHERE pa.block_id = b.id
        """
    )
    op.alter_column("plan_activities", "farm_id", nullable=False)
    op.create_foreign_key(
        "fk_plan_activities_farm_id_farms",
        "plan_activities",
        "farms",
        ["farm_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_plan_activities_farm_id_scheduled_date",
        "plan_activities",
        ["farm_id", "scheduled_date"],
    )

    # ---- plan_id becomes nullable --------------------------------------
    op.alter_column("plan_activities", "plan_id", nullable=True)

    # ---- recommendation_id (nullable FK to recommendations) ------------
    op.add_column(
        "plan_activities",
        sa.Column(
            "recommendation_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_plan_activities_recommendation_id_recommendations",
        "plan_activities",
        "recommendations",
        ["recommendation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_plan_activities_recommendation_id",
        "plan_activities",
        ["recommendation_id"],
        postgresql_where=sa.text("recommendation_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_plan_activities_recommendation_id", table_name="plan_activities"
    )
    op.drop_constraint(
        "fk_plan_activities_recommendation_id_recommendations",
        "plan_activities",
        type_="foreignkey",
    )
    op.drop_column("plan_activities", "recommendation_id")

    # Restore plan_id NOT NULL only if no NULL rows exist; otherwise
    # block downgrade to avoid silent data loss.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM plan_activities WHERE plan_id IS NULL) THEN
            RAISE EXCEPTION 'cannot downgrade: plan_activities rows have NULL plan_id';
          END IF;
        END $$;
        """
    )
    op.alter_column("plan_activities", "plan_id", nullable=False)

    op.drop_index(
        "ix_plan_activities_farm_id_scheduled_date", table_name="plan_activities"
    )
    op.drop_constraint(
        "fk_plan_activities_farm_id_farms",
        "plan_activities",
        type_="foreignkey",
    )
    op.drop_column("plan_activities", "farm_id")
