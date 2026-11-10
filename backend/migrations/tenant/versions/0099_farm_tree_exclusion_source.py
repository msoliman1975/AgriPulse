"""Record who turned a tree off for a farm: the farm, or the whole tenant.

`farm_tree_exclusions` (tenant 0089) holds a row per farm per tree turned
off. Two kinds of writer put rows there:

  * a farm manager unticking one tree in the farm's settings ("farm");
  * the tenant-wide switch on the tree page, and "copy this platform tree and
    turn the original off", which write a row on every farm at once
    ("tenant").

Since #806 a change to a farm's crops, soil, country or blocks clears the
farm's "off" rows for trees that no longer match any of its blocks, so the
tree comes back on if the crop does. That is right for a farm's own choice,
which was about the crop it had. It is wrong for a tenant-wide one: the
tenant said "not on any farm", and clearing it on a farm that happened not to
match yet let the tree run there the day the crop arrived.

`source` tells the two apart. Only 'farm' rows are cleared when a tree stops
matching. 'tenant' rows stay until somebody turns the tree back on, for that
farm or everywhere.

Backfill: a tenant-wide write lands on every farm in ONE statement, and
`disabled_at` defaults to `public.app_now()`, which is fixed for a statement.
So rows that share `(tree_id, disabled_at)` across more than one farm were
written together, by a tenant-wide action. A farm's own toggle is one row in
its own request. The one case this cannot see is a tenant with a single farm,
where a tenant-wide write is one row; it is left as 'farm', and on a
one-farm tenant the two mean the same thing.

Revision ID: 0099
Revises: 0098
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0099"
down_revision: str | Sequence[str] | None = "0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "farm_tree_exclusions",
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'farm'")),
    )
    # Raw SQL so the name is the literal one: the metadata naming convention
    # rewrites names given to op.create_check_constraint (see tenant 0089).
    op.execute(
        "ALTER TABLE farm_tree_exclusions ADD CONSTRAINT "
        "ck_farm_tree_exclusions_source_known CHECK (source IN ('farm', 'tenant'))"
    )
    op.execute(
        """
        UPDATE farm_tree_exclusions x
           SET source = 'tenant'
          FROM (
                SELECT tree_id, disabled_at
                  FROM farm_tree_exclusions
                 GROUP BY tree_id, disabled_at
                HAVING count(*) > 1
               ) together
         WHERE x.tree_id = together.tree_id
           AND x.disabled_at = together.disabled_at
        """
    )


def downgrade() -> None:
    # Dropping the column drops its CHECK with it.
    op.drop_column("farm_tree_exclusions", "source")
