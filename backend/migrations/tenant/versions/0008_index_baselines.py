"""Index baselines + baseline_deviation on block_index_aggregates.

PR-4 of FarmDM rollout. Today's `block_index_aggregates` rows carry
absolute per-scene stats (mean/min/max/std + percentiles). Alerts and
recommendations need to ask "is this block doing well *relative to
its own history*?" — comparing absolute NDVI hides that a young
orchard with 0.45 NDVI is fine while a mature one with 0.45 is sick.

Two pieces:

  * `block_index_baselines` — one row per (block, index, day-of-year)
    holding the long-running mean and std over a rolling history
    window. Computed by a Beat task weekly; populated incrementally as
    new years of data arrive. ``window_days`` is stored on the row so
    the smoothing window can change without orphaning previous
    baselines (consumers read whichever rows they last computed).
  * `block_index_aggregates.baseline_deviation` — nullable NUMERIC,
    written at index-compute time as the z-score of this row's
    `mean` against the matching baseline. NULL when no baseline
    exists (new blocks, first-year rows). Alerts engine reads this
    instead of recomputing per-evaluation.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "block_index_baselines",
        sa.Column(
            "block_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("blocks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("index_code", sa.Text(), nullable=False),
        sa.Column("day_of_year", sa.SmallInteger(), nullable=False),
        sa.Column("baseline_mean", sa.Numeric(8, 4), nullable=False),
        sa.Column("baseline_std", sa.Numeric(8, 4), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column(
            "window_days",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("7"),
        ),
        sa.Column("years_observed", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "block_id", "index_code", "day_of_year", name="pk_block_index_baselines"
        ),
    )
    op.create_check_constraint(
        "ck_block_index_baselines_doy_range",
        "block_index_baselines",
        "day_of_year BETWEEN 1 AND 366",
    )
    op.create_check_constraint(
        "ck_block_index_baselines_sample_count_positive",
        "block_index_baselines",
        "sample_count >= 1",
    )

    op.add_column(
        "block_index_aggregates",
        sa.Column(
            "baseline_deviation",
            sa.Numeric(8, 4),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("block_index_aggregates", "baseline_deviation")
    op.drop_constraint(
        "ck_block_index_baselines_sample_count_positive",
        "block_index_baselines",
        type_="check",
    )
    op.drop_constraint(
        "ck_block_index_baselines_doy_range",
        "block_index_baselines",
        type_="check",
    )
    op.drop_table("block_index_baselines")
