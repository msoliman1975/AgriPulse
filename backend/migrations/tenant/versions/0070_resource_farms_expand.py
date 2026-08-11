"""Workers and equipment become tenant-level — the expand half (W2-A).

``resources`` has carried ``farm_id UUID NOT NULL`` since 0031, which makes a
person who works two farms *two rows*. That is why "what has this person done"
has no answer, and why ``ix_resources_membership_id`` cannot be unique: both
rows legitimately point at the same membership. Nothing that resolves a signed-in
user to their work can be built while that is true.

The replacement mirrors ``farm_scopes``, which is already this codebase's answer
to "one person, N farms": the roster row becomes tenant-level and a separate
``resource_farms`` table carries the set of farms it is available on. The
rejected alternative — a nullable ``farm_id`` where NULL means tenant-wide — is
binary (it cannot say "two of our five farms") and would seed
``(farm_id = :x OR farm_id IS NULL)`` into every query in the module forever.

**This migration is deliberately additive.** It creates the table, backfills it
1:1, and only *relaxes* ``farm_id`` to nullable. Dropping the column, re-scoping
the unique-name index to the tenant and making ``membership_id`` unique all wait
for 0071, after the code that stops reading ``farm_id`` is live. Image tags roll
back and migrations do not, so the schema in between has to serve both.

The backfill is strictly one row per resource: **no dedup and no auto-merge.**
Name equality is not identity — two farms each having a "Tractor 1" is normal —
and merging silently rewrites activity history across farms.

Revision ID: 0070
Revises: 0069
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resource_farms",
        sa.Column(
            "resource_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "farm_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # "Who is available here" is the read this table exists for, and it is the
    # one the composite PK (resource first) cannot serve.
    op.create_index("ix_resource_farms_farm_id", "resource_farms", ["farm_id"])

    # 1:1. Every existing row keeps exactly the farm it already had.
    op.execute(
        """
        INSERT INTO resource_farms (resource_id, farm_id)
        SELECT id, farm_id FROM resources
        ON CONFLICT DO NOTHING
        """
    )

    # Relaxed, not dropped: the old code still writes it, and this migration
    # has to leave the schema usable by the image currently running.
    op.alter_column(
        "resources", "farm_id", existing_type=sa.dialects.postgresql.UUID(), nullable=True
    )

    # And the cascade has to go, or none of the above matters.
    #
    # `fk_resources_farm_id_farms` is ON DELETE CASCADE, which is how farm
    # purge cleaned up workers before this. Left in place it still fires:
    # deleting a farm hard-deletes every worker whose vestigial `farm_id`
    # happens to point at it — including people who work other farms, and
    # taking their `activity_resources` history on those farms with them.
    # Re-created as SET NULL so the column stays referentially honest until
    # 0071 removes it, and so a farm deletion empties the field rather than
    # the row. Ownership now lives entirely in `resource_farms`, whose own
    # FK cascade correctly removes just the link.
    #
    # The name is read from the catalog rather than assumed: Postgres
    # truncates and hash-suffixes at 63 characters, so a convention-derived
    # guess is wrong exactly when the name is long.
    op.execute(
        """
        DO $$
        DECLARE fk_name text;
        BEGIN
            SELECT conname INTO fk_name
              FROM pg_constraint
             WHERE conrelid = 'resources'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(
                     SELECT attnum FROM pg_attribute
                      WHERE attrelid = 'resources'::regclass AND attname = 'farm_id'
                   )]::smallint[];
            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE resources DROP CONSTRAINT %I', fk_name);
            END IF;
            ALTER TABLE resources
                ADD CONSTRAINT fk_resources_farm_id_farms
                FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE SET NULL;
        END $$
        """
    )


def downgrade() -> None:
    # Put the cascade back first: the pre-0070 world deletes workers with
    # their farm, and leaving SET NULL behind would silently change that.
    op.execute(
        """
        DO $$
        DECLARE fk_name text;
        BEGIN
            SELECT conname INTO fk_name
              FROM pg_constraint
             WHERE conrelid = 'resources'::regclass
               AND contype = 'f'
               AND conkey = ARRAY[(
                     SELECT attnum FROM pg_attribute
                      WHERE attrelid = 'resources'::regclass AND attname = 'farm_id'
                   )]::smallint[];
            IF fk_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE resources DROP CONSTRAINT %I', fk_name);
            END IF;
            ALTER TABLE resources
                ADD CONSTRAINT fk_resources_farm_id_farms
                FOREIGN KEY (farm_id) REFERENCES farms(id) ON DELETE CASCADE;
        END $$
        """
    )

    # Re-tightening `farm_id` needs every row to have one. A resource created
    # after the expand — tenant-level, possibly on several farms or none — has
    # nothing to put back, so pick its earliest farm and fail loudly if even
    # that is missing rather than inventing one.
    op.execute(
        """
        UPDATE resources r
           SET farm_id = (
                 SELECT rf.farm_id FROM resource_farms rf
                  WHERE rf.resource_id = r.id
                  ORDER BY rf.created_at, rf.farm_id
                  LIMIT 1
               )
         WHERE r.farm_id IS NULL
        """
    )
    op.execute(
        """
        DO $$
        DECLARE orphans int;
        BEGIN
            SELECT count(*) INTO orphans FROM resources WHERE farm_id IS NULL;
            IF orphans > 0 THEN
                -- USING MESSAGE, not RAISE's format string: its placeholder
                -- is a percent sign, which psycopg reads as a parameter
                -- marker and mangles before Postgres ever sees it.
                RAISE EXCEPTION USING MESSAGE =
                    'cannot downgrade: ' || orphans
                    || ' resource(s) belong to no farm';
            END IF;
        END $$
        """
    )
    op.alter_column(
        "resources", "farm_id", existing_type=sa.dialects.postgresql.UUID(), nullable=False
    )
    op.drop_index("ix_resource_farms_farm_id", table_name="resource_farms")
    op.drop_table("resource_farms")
