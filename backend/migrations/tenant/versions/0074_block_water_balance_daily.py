"""Per-block daily crop water balance (indices-guide gap audit, finding D7).

One per-tenant **regular** table, ``block_water_balance_daily``, holding the
crop-specific water accounting the guide's Water Balance Index actually
specifies: ``precipitation + irrigation - ETc``.

**Why block-keyed rather than another `weather_index_daily` row.** That table
is farm-keyed (PK ``farm_id, date, index_code``), but both new terms vary by
block: Kc comes from the block's crop and growth stage, and irrigation volume
is recorded per block on ``irrigation_schedules``. A farm-level ETc would have
to pick one crop coefficient for every block on the farm, which on a mixed
planting is wrong for all but one of them. ``weather_risk_daily`` (0050) set
this precedent for exactly the same reason: "raw indices are farm-uniform, but
[the reading] folds in each block's crop + growth stage".

**What this replaces.** ``rain_et_balance`` computes ``precip - ET0``, and
``evaporation_coeff`` a rolling ``sum(ET0 - precip)``. Both substitute ET0 —
climatic demand over a reference grass surface — for what a mango canopy
actually transpires, and both ignore irrigation entirely. Every block we serve
is irrigated, so those two report a deficit that is not there. They are kept:
they are honest climatic indices, farm-wide and available for every farm
regardless of whether irrigation is being logged. This table is the crop-level
answer beside them.

Deliberately NOT seeded into ``weather_indices_catalog``: the observer's
weather lane counts active catalog rows against codes present in
``weather_index_daily``, so a catalog row with no farm-keyed rows behind it
reports a permanent coverage shortfall.

Columns keep the whole derivation rather than just the answer, so a reader can
see WHY a balance is negative — whether demand was high, rain absent, or
irrigation simply not logged — which is the difference between a number that
can be acted on and one that has to be trusted.

Revision ID: 0074
Revises: 0073
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074"
down_revision: str | Sequence[str] | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "block_water_balance_daily",
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        # --- the answer ---
        # precip + irrigation - etc. Negative = deficit to irrigate against;
        # strongly positive = risk of waterlogging.
        sa.Column("balance_mm", sa.Numeric(8, 2), nullable=False),
        # --- the derivation, so the answer can be argued with ---
        sa.Column("etc_mm", sa.Numeric(8, 2), nullable=False),
        sa.Column("et0_mm", sa.Numeric(8, 2), nullable=False),
        # The crop coefficient actually used, and where it came from. Kc
        # resolves crop phenology JSONB -> code default -> generic default, and
        # a balance built on the generic 0.85 fallback deserves less confidence
        # than one built on a per-stage value. Without recording it, the two
        # are indistinguishable after the fact.
        sa.Column("kc_used", sa.Numeric(4, 2), nullable=False),
        sa.Column("kc_source", sa.Text(), nullable=False),
        sa.Column("growth_stage", sa.Text(), nullable=True),
        sa.Column("precip_mm", sa.Numeric(8, 2), nullable=False, server_default=sa.text("0")),
        # Sum of `applied_volume_mm` over irrigation_schedules marked applied
        # for this block-day. Zero means "none logged", which is NOT the same
        # as "none applied" — `irrigation_logged` carries that distinction.
        sa.Column("irrigation_mm", sa.Numeric(8, 2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "irrigation_logged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("block_id", "date", name="pk_block_water_balance_daily"),
        sa.CheckConstraint(
            "kc_source IN ('phenology', 'stage_default', 'generic_default')",
            name="ck_block_water_balance_daily_kc_source",
        ),
        sa.CheckConstraint("kc_used > 0", name="ck_block_water_balance_daily_kc_positive"),
        sa.CheckConstraint(
            "etc_mm >= 0 AND et0_mm >= 0 AND precip_mm >= 0 AND irrigation_mm >= 0",
            name="ck_block_water_balance_daily_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name="fk_block_water_balance_daily_block_id_blocks",
            ondelete="CASCADE",
        ),
    )
    # The read pattern is "this block, recent days" (dock chart, condition
    # snapshot) — served by the PK — and "this day, every block" for the sweep's
    # own upsert. A date index covers the second without duplicating the first.
    op.create_index(
        "ix_block_water_balance_daily_date",
        "block_water_balance_daily",
        ["date"],
    )


def downgrade() -> None:
    op.drop_index("ix_block_water_balance_daily_date", table_name="block_water_balance_daily")
    op.drop_table("block_water_balance_daily")
