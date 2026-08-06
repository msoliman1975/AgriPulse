"""Crop assignments get valid time, so "current" stops being a stored guess.

``block_crops.is_current`` is a *stored boolean*, flipped only when someone
assigns a new crop. Nothing re-evaluates it as time passes, so a potato
assignment that finished in March still reads as current in August — on the
map, in the block drawer, and in the decision-tree context that resolves the
block's crop. "Current" today means **most recently assigned**, not **active
now**.

This adds **valid time** alongside the existing agronomic dates rather than
reinterpreting them, the same separation ``grid_configs`` made in 0054:

``effective_from`` / ``effective_to``
    The period this assignment governs. ``effective_to IS NULL`` means
    open-ended — a perennial orchard has no end until it is grubbed up. The
    range is **half-open**, ``[from, to)``: the last day under the crop is
    the day before ``effective_to``, which is what makes an assignment ending
    and the next one starting on the same date adjacent rather than
    overlapping.

``planting_date`` / ``actual_harvest_date`` stay exactly as they are. They are
agronomic events; these are the record's validity. They usually coincide, but
a transplanted tree's establishment and its planting date can differ, and for
a perennial the harvest is emphatically not the end of occupancy.

Non-overlap is enforced by an EXCLUDE constraint, not by service code: bulk
AOI upload, backfills and any future writer all bypass the service, and a
constraint cannot be forgotten.

Backfill, chosen so no row becomes less visible than it is today
--------------------------------------------------------------
* ``effective_from`` := ``planting_date``, else the row's ``created_at`` date.
* ``effective_to``   := the *next* assignment's ``effective_from`` (ordered by
  from, then created_at). This makes the sequence adjacent by construction, so
  the exclusion constraint can be created without inventing gaps.
* the row with ``is_current = TRUE`` gets ``effective_to = NULL``, **whatever
  its harvest date says**. Deriving its end from ``actual_harvest_date`` would
  silently un-assign every block whose crop has been harvested — correct in
  theory, a visible regression in production on the day this deploys.
* a trailing non-current row with nothing after it gets
  ``COALESCE(actual_harvest_date, expected_harvest_end, updated_at::date)``,
  clamped to at least ``effective_from + 1 day``.

If two assignments still overlap after that, the migration **raises with the
block ids** instead of guessing. A silent fix here would be a silent rewrite
of someone's cropping history.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("block_crops", sa.Column("effective_from", sa.Date(), nullable=True))
    op.add_column("block_crops", sa.Column("effective_to", sa.Date(), nullable=True))

    # --- from: the planting date, else when the row was created ------------
    op.execute(
        """
        UPDATE block_crops
           SET effective_from = COALESCE(planting_date, created_at::date)
         WHERE deleted_at IS NULL
        """
    )

    # --- to: the next assignment's start, so the sequence is adjacent ------
    # `is_current` rows are excluded from getting a `to` here and below: they
    # stay open so nothing that reads as assigned today stops doing so.
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   block_id,
                   effective_from,
                   LEAD(effective_from) OVER (
                       PARTITION BY block_id
                       ORDER BY effective_from, created_at
                   ) AS next_from
              FROM block_crops
             WHERE deleted_at IS NULL
        )
        UPDATE block_crops bc
           SET effective_to = o.next_from
          FROM ordered o
         WHERE bc.id = o.id
           AND o.next_from IS NOT NULL
           AND o.next_from > o.effective_from
           AND bc.is_current = FALSE
        """
    )

    # --- trailing non-current rows: fall back to a harvest date ------------
    op.execute(
        """
        UPDATE block_crops
           SET effective_to = GREATEST(
                   COALESCE(actual_harvest_date, expected_harvest_end, updated_at::date),
                   effective_from + INTERVAL '1 day'
               )::date
         WHERE deleted_at IS NULL
           AND is_current = FALSE
           AND effective_to IS NULL
        """
    )

    # Soft-deleted rows never took part in the walk above but the column is
    # about to go NOT NULL, so give them a degenerate one-day range. They are
    # excluded from the exclusion constraint, so this cannot collide.
    op.execute(
        """
        UPDATE block_crops
           SET effective_from = COALESCE(effective_from, planting_date, created_at::date),
               effective_to   = COALESCE(
                   effective_to,
                   (COALESCE(planting_date, created_at::date) + INTERVAL '1 day')::date
               )
         WHERE deleted_at IS NOT NULL
        """
    )

    # --- refuse to guess -----------------------------------------------------
    conflicts = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT a.block_id, a.id AS a_id, b.id AS b_id
                  FROM block_crops a
                  JOIN block_crops b
                    ON a.block_id = b.block_id
                   AND a.id < b.id
                   AND a.deleted_at IS NULL
                   AND b.deleted_at IS NULL
                   AND daterange(a.effective_from, a.effective_to)
                    && daterange(b.effective_from, b.effective_to)
                 LIMIT 20
                """
            )
        )
        .all()
    )
    if conflicts:
        listed = ", ".join(f"block={r.block_id} ({r.a_id} vs {r.b_id})" for r in conflicts)
        raise RuntimeError(
            "block_crops has overlapping assignments that this migration will not "
            "resolve on its own — the fix is a business decision, not a default. "
            f"Overlapping pairs (first 20): {listed}"
        )

    op.alter_column("block_crops", "effective_from", nullable=False)

    # `btree_gist` is what lets a plain `=` on block_id share a GiST index with
    # the range overlap operator.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        """
        ALTER TABLE block_crops
          ADD CONSTRAINT ex_block_crops_no_overlap
          EXCLUDE USING gist (
              block_id WITH =,
              daterange(effective_from, effective_to) WITH &&
          ) WHERE (deleted_at IS NULL)
        """
    )

    # The read path is "the assignment whose range contains today", per block.
    op.create_index(
        "ix_block_crops_block_validity",
        "block_crops",
        ["block_id", "effective_from", "effective_to"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_block_crops_block_validity", table_name="block_crops")
    op.execute("ALTER TABLE block_crops DROP CONSTRAINT IF EXISTS ex_block_crops_no_overlap")
    op.drop_column("block_crops", "effective_to")
    op.drop_column("block_crops", "effective_from")
    # btree_gist is left installed: other objects may have started using it,
    # and dropping an extension a later migration relies on is worse than
    # leaving one behind.
