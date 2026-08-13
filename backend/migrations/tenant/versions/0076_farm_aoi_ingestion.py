"""Fetch imagery for the FARM boundary, not one AOI per block.

Today a 36-block farm turns one satellite pass into 36 rasters and no pixels
at all between them — on the reference farm that is 50.3 of 203.4 feddan not
merely uncoloured but unmeasured. The farm surface shipped in 0073 stitches
those 36 together, so it inherits the same hole.

This adds what a real farm-AOI fetch needs, and nothing else:

* ``imagery_farm_ingestion_jobs`` — its own table rather than a nullable
  ``block_id`` on ``imagery_ingestion_jobs``. That table is the hot path for
  every farm's daily imagery and its idempotency key is
  ``UNIQUE(subscription_id, scene_id)``; widening it to mean two things is how
  a working pipeline gets broken by a feature nobody has switched on yet.
* ``farm_scene_rasters.source`` — a surface is now either ``stitched`` from
  block rasters or ``fetched`` for the farm boundary, and the console should
  never have to guess which it is looking at. Existing rows are stitched.
* ``farm_scene_rasters.blocks_merged`` becomes nullable, because a fetched
  surface merged no blocks and 0 would read as "merged nothing" rather than
  "the question does not apply".
* ``imagery_farm_subscriptions.fetch_farm_aoi`` — the per-farm switch,
  defaulting to FALSE. 0074 activated a farm subscription for every farm that
  had block subscriptions, so without this column deploying the ingestion task
  would start fetching a second, larger AOI for every farm on the platform.
  Cutover stays a per-farm decision, the way the raster rebuild is.

Revision ID: 0076
Revises: 0075
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "imagery_farm_ingestion_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("imagery_farm_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("farms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Logical reference to public.imagery_products — never a real FK
        # across the schema boundary.
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("scene_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("cloud_cover_pct", sa.Numeric(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("stac_item_id", sa.Text(), nullable=True),
        sa.Column("assets_written", postgresql.JSONB(), nullable=True),
    )
    # Same idempotency contract as the block table: re-discovering a scene must
    # not spawn a second job.
    op.create_index(
        "uq_imagery_farm_jobs_subscription_scene",
        "imagery_farm_ingestion_jobs",
        ["subscription_id", "scene_id"],
        unique=True,
    )
    # The console and the rebuild both ask "what does this farm have, newest
    # first"; the acquire path asks "what is still pending".
    op.create_index(
        "ix_imagery_farm_jobs_farm_scene_dt",
        "imagery_farm_ingestion_jobs",
        ["farm_id", sa.text("scene_datetime DESC")],
    )
    op.create_index(
        "ix_imagery_farm_jobs_status",
        "imagery_farm_ingestion_jobs",
        ["status"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.add_column(
        "farm_scene_rasters",
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'stitched'")),
    )
    op.create_check_constraint(
        "ck_farm_scene_rasters_source",
        "farm_scene_rasters",
        "source IN ('stitched', 'fetched')",
    )
    op.alter_column("farm_scene_rasters", "blocks_merged", nullable=True)

    op.add_column(
        "imagery_farm_subscriptions",
        sa.Column(
            "fetch_farm_aoi",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("imagery_farm_subscriptions", "fetch_farm_aoi")
    # A fetched surface has no blocks_merged; drop those rows rather than
    # invent a count to satisfy the NOT NULL going back.
    op.execute("DELETE FROM farm_scene_rasters WHERE source = 'fetched'")
    op.alter_column("farm_scene_rasters", "blocks_merged", nullable=False)
    op.drop_constraint("ck_farm_scene_rasters_source", "farm_scene_rasters", type_="check")
    op.drop_column("farm_scene_rasters", "source")
    op.drop_index("ix_imagery_farm_jobs_status", table_name="imagery_farm_ingestion_jobs")
    op.drop_index("ix_imagery_farm_jobs_farm_scene_dt", table_name="imagery_farm_ingestion_jobs")
    op.drop_index(
        "uq_imagery_farm_jobs_subscription_scene", table_name="imagery_farm_ingestion_jobs"
    )
    op.drop_table("imagery_farm_ingestion_jobs")
