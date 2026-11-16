"""Harvest records (investor app v2, build plan 3.5).

One row per pick on a block: the date, the weight and, when known, the price
per kilogram. Staff record them; PR 6 scales them to each investor's holding
(decision D1) and shows gross revenue (D2). ``notes_internal`` never leaves
staff screens.

``currency`` is copied from the tenant's ``default_currency`` when the row is
written, so a later change of the tenant setting does not reprice history.
``pick_no`` numbers the picks within a block and season.

Additive: a new table, no backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0111"
down_revision: str | Sequence[str] | None = "0110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE harvest_lots (
            id uuid PRIMARY KEY DEFAULT uuid_generate_v7(),
            farm_id uuid NOT NULL REFERENCES farms (id) ON DELETE CASCADE,
            block_id uuid NOT NULL REFERENCES blocks (id) ON DELETE CASCADE,
            block_crop_id uuid REFERENCES block_crops (id) ON DELETE SET NULL,
            season_label text NOT NULL,
            pick_no integer NOT NULL CHECK (pick_no >= 1),
            label text,
            label_ar text,
            harvested_on date NOT NULL,
            weight_kg numeric(12, 2) NOT NULL CHECK (weight_kg > 0),
            price_per_kg numeric(12, 4) CHECK (price_per_kg IS NULL OR price_per_kg >= 0),
            currency char(3) NOT NULL,
            notes_internal text,
            created_by uuid,
            updated_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            deleted_at timestamptz
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_harvest_lots_block_day "
        "ON harvest_lots (block_id, harvested_on) WHERE deleted_at IS NULL"
    )
    # One live pick number per block and season.
    op.execute(
        "CREATE UNIQUE INDEX uq_harvest_lots_pick "
        "ON harvest_lots (block_id, season_label, pick_no) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE TRIGGER trg_harvest_lots_updated_at BEFORE UPDATE ON harvest_lots "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS harvest_lots")
