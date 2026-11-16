"""Photos on plan activities (investor app v2, build plan 3.3).

A field worker can attach photos when they complete an activity; staff see
them on the activity, and the investor app (PR 4) shows the visible ones for
the investor's own holding. ``hidden_from_investors`` is the per-photo
switch of decision D5: photos reach investors automatically unless staff
hide one.

The object lives in the uploads bucket under
``tenants/<tenant>/farms/<farm>/activity-photos/<activity>/``; this row only
points at it. ``s3_key`` is unique so a key cannot be attached twice.
``created_by`` is a plain uuid, like ``field_flags.raised_by``: users live in
``public`` and are never joined across from here.

Additive: a new table, no backfill, nothing existing changes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0110"
down_revision: str | Sequence[str] | None = "0109"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE plan_activity_photos (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            activity_id uuid NOT NULL
                REFERENCES plan_activities (id) ON DELETE CASCADE,
            s3_key text NOT NULL UNIQUE,
            taken_at timestamptz,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            hidden_from_investors boolean NOT NULL DEFAULT FALSE,
            deleted_at timestamptz
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_plan_activity_photos_activity "
        "ON plan_activity_photos (activity_id, created_at) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_plan_activity_photos_activity")
    op.execute("DROP TABLE IF EXISTS plan_activity_photos")
