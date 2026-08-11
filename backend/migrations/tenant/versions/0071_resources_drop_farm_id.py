"""Workers and equipment become tenant-level — the contract half (W3-A).

0070 added ``resource_farms``, backfilled it 1:1 and relaxed
``resources.farm_id``. This drops the column and re-scopes everything that
was keyed on it.

**Do not apply this until the image that stopped reading ``farm_id`` is live**
— which is the whole reason it is a separate migration. Tags roll back and
migrations do not.

Two indexes change meaning, and both are the point of the exercise:

* ``uq_resources_farm_kind_active_name`` was ``(farm_id, kind, lower(name))``.
  Tenant-wide it becomes ``(kind, lower(name))``, so one name is one thing
  across the whole tenant rather than per farm. **This is the migration's one
  way to fail on real data**: two farms each having a "Tractor 1" is entirely
  normal and would collide. The pre-flight scan below raises with the actual
  offending names rather than letting Postgres emit a bare duplicate-key
  error, because the fix is a human deciding whether those are the same
  tractor.

* ``ix_resources_membership_id`` becomes **UNIQUE**. One person, one worker
  row — the property that makes "what has this person done" answerable, and
  the reason ``GET /me/work`` can resolve a signed-in user at all. It could
  not be unique before: somebody working two farms legitimately had two rows.

Revision ID: 0071
Revises: 0070
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: str | None = "0070"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Fail loudly, and say what to fix. A bare unique-violation from the
    # CREATE INDEX names one arbitrary row and no context.
    # No `%` anywhere in these blocks on purpose: psycopg reads it as a
    # parameter placeholder, so `format()` and RAISE's own substitution both
    # arrive mangled. Plain concatenation says the same thing and survives
    # the driver untouched.
    op.execute(
        """
        DO $$
        DECLARE clashes text;
        BEGIN
            SELECT string_agg(kind || ' "' || lname || '" x' || n, ', ')
              INTO clashes
              FROM (
                    SELECT kind, lower(name) AS lname, count(*) AS n
                      FROM resources
                     WHERE archived_at IS NULL AND deleted_at IS NULL
                     GROUP BY kind, lower(name)
                    HAVING count(*) > 1
                   ) dupes;
            IF clashes IS NOT NULL THEN
                -- USING MESSAGE takes an expression; RAISE's own first
                -- argument is a format string, and its placeholder is the
                -- one character psycopg will not pass through intact.
                RAISE EXCEPTION USING MESSAGE =
                    'cannot make resource names tenant-unique. Rename or merge first: '
                    || clashes;
            END IF;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        DECLARE clashes text;
        BEGIN
            SELECT string_agg(membership_id::text, ', ') INTO clashes
              FROM (
                    SELECT membership_id
                      FROM resources
                     WHERE membership_id IS NOT NULL
                       AND archived_at IS NULL AND deleted_at IS NULL
                     GROUP BY membership_id
                    HAVING count(*) > 1
                   ) dupes;
            IF clashes IS NOT NULL THEN
                RAISE EXCEPTION
                    'membership(s) hold several worker rows; merge before making membership_id unique';
            END IF;
        END $$
        """
    )

    op.execute("DROP INDEX IF EXISTS uq_resources_farm_kind_active_name")
    op.execute("DROP INDEX IF EXISTS ix_resources_farm_kind_archived")
    op.execute("DROP INDEX IF EXISTS ix_resources_membership_id")

    op.execute(
        """
        CREATE UNIQUE INDEX uq_resources_kind_active_name
        ON resources (kind, lower(name))
        WHERE archived_at IS NULL AND deleted_at IS NULL
        """
    )
    op.execute("CREATE INDEX ix_resources_kind_archived ON resources (kind, archived_at)")
    # One person, one row. The constraint the whole promotion was for.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_resources_membership_id
        ON resources (membership_id)
        WHERE membership_id IS NOT NULL AND archived_at IS NULL AND deleted_at IS NULL
        """
    )

    # The FK went to SET NULL in 0070; dropping the column takes it with it.
    op.drop_column("resources", "farm_id")


def downgrade() -> None:
    op.add_column(
        "resources",
        sa.Column("farm_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Restore a single farm per row from the availability set — the earliest
    # link, matching what 0070's own downgrade picks.
    op.execute(
        """
        UPDATE resources r
           SET farm_id = (
                 SELECT rf.farm_id FROM resource_farms rf
                  WHERE rf.resource_id = r.id
                  ORDER BY rf.created_at, rf.farm_id
                  LIMIT 1
               )
        """
    )
    op.execute(
        """
        ALTER TABLE resources
            ADD CONSTRAINT fk_resources_farm_id_farms
            FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE SET NULL
        """
    )

    op.execute("DROP INDEX IF EXISTS uq_resources_membership_id")
    op.execute("DROP INDEX IF EXISTS ix_resources_kind_archived")
    op.execute("DROP INDEX IF EXISTS uq_resources_kind_active_name")

    # Back to the per-farm shapes 0031 created.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_resources_farm_kind_active_name
        ON resources (farm_id, kind, lower(name))
        WHERE archived_at IS NULL AND deleted_at IS NULL
        """
    )
    op.execute(
        "CREATE INDEX ix_resources_farm_kind_archived ON resources (farm_id, kind, archived_at)"
    )
    op.execute(
        """
        CREATE INDEX ix_resources_membership_id
        ON resources (membership_id)
        WHERE membership_id IS NOT NULL AND deleted_at IS NULL
        """
    )
