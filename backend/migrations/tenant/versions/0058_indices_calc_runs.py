"""Calculation lineage for the indices pipeline — ``indices_calc_runs``.

One row per **execution** of ``imagery.compute_indices`` for a
(scene, block, product). Written by the task; read by Observer.

**Why a side table rather than columns on ``block_index_aggregates``.**

Three reasons, in increasing order of importance.

1. That hypertable carries two continuous aggregates (``block_index_daily``,
   ``block_index_weekly``) on the customer read path, so altering it drags a
   CAGG dependency into every schema change.

2. Columns can only ever hold the *latest* execution. Aggregate rows are
   upserted on the composite key, so a recompute silently replaces the
   previous numbers — and one of the things Observer exists to expose is
   precisely that a row was quietly overwritten by a different code version.
   A column-based stamp cannot show a history it has already overwritten.

3. One row per execution covers all seven indices at once, since they share
   the AOI footprint, the mask decision and the timings. That is about a
   seventh of the volume of a per-index run table, with the per-index detail
   (valid / no-data counts, mean) kept in ``per_index`` JSONB.

**Not a hypertable, and no retention policy.** Growth is roughly one row per
scene per block: a 36-block farm over a decade of dense backfill is ~25k
rows. More to the point, a retention policy on a *lineage* table would
silently delete the audit trail that justifies the table existing. Revisit if
a tenant ever crosses ~10M rows; converting later is not blocked by shipping
it flat now.

``masked_pixel_count`` and the per-index ``nodata`` counts close the gap that
makes "why is this scene 43% valid?" unanswerable today: the aggregate row
stores valid and total counts and nothing that separates a cloud-masked pixel
from a sensor gap.

Revision ID: 0058
Revises: 0057
Create Date: 2026-08-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: str | Sequence[str] | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# What caused this execution. `verify` never writes aggregates — an Observer
# verification records that it ran without claiming to have produced the
# stored numbers.
_TRIGGERS = "'live', 'backfill', 'verify', 'manual'"
_OUTCOMES = "'ok', 'failed'"


def upgrade() -> None:
    op.create_table(
        "indices_calc_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v7()"),
        ),
        # No FK: a purge of an ingestion job must not be blocked by lineage,
        # and lineage outliving the job row is the point of keeping it.
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scene_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("stac_item_id", sa.Text(), nullable=True),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aoi_hash", sa.Text(), nullable=True),
        # The geometry this execution actually gridded against, resolved by
        # the scene's own time (tenant 0054). NULL = the block was ungridded
        # at that moment, which is not the same as "no cells were written".
        sa.Column("grid_config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cell_count", sa.Integer(), nullable=True),
        # Bumped when the formulas or the masking rules change, so a stored
        # number can be attributed to the code that produced it.
        sa.Column("calc_version", sa.Text(), nullable=False),
        sa.Column("mask_ruleset", sa.Text(), nullable=False),
        sa.Column("band_order", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("aoi_pixel_count", sa.Integer(), nullable=True),
        sa.Column("masked_pixel_count", sa.Integer(), nullable=True),
        sa.Column(
            "per_index",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("trigger", sa.Text(), nullable=False, server_default=sa.text("'live'")),
        sa.Column("outcome", sa.Text(), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # The `name=` here is the convention's `%(constraint_name)s` slot, not
        # the final identifier: metadata naming renders these as
        # `ck_indices_calc_runs_<name>`. Passing the full name produces
        # `ck_indices_calc_runs_ck_indices_calc_runs_trigger`, which downgrade
        # then fails to drop — the doubling bug this repo has hit before.
        sa.CheckConstraint(f"trigger IN ({_TRIGGERS})", name="trigger"),
        sa.CheckConstraint(f"outcome IN ({_OUTCOMES})", name="outcome"),
        sa.CheckConstraint(
            "masked_pixel_count IS NULL"
            " OR aoi_pixel_count IS NULL"
            " OR masked_pixel_count <= aoi_pixel_count",
            name="masked_within_aoi",
        ),
    )

    # The read Observer actually performs: "history for this scene, newest
    # first", served by the index rather than by a sort.
    #
    # `id` is part of the ordering because `created_at` defaults to now() —
    # the *transaction* timestamp — so two runs recorded in one transaction
    # share it exactly and the ordering would not be total. uuid_generate_v7
    # is time-ordered, which breaks the tie in the right direction.
    op.create_index(
        "ix_indices_calc_runs_scene",
        "indices_calc_runs",
        [
            "block_id",
            "product_id",
            "scene_time",
            sa.text("created_at DESC"),
            sa.text("id DESC"),
        ],
    )
    # The overview's "which calc versions are present in this window" query.
    op.create_index(
        "ix_indices_calc_runs_version_window",
        "indices_calc_runs",
        ["scene_time", "calc_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_indices_calc_runs_version_window", table_name="indices_calc_runs")
    op.drop_index("ix_indices_calc_runs_scene", table_name="indices_calc_runs")
    op.drop_table("indices_calc_runs")
