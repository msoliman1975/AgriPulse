"""imagery_farm_subscriptions — subscribe a FARM to a product, not a block.

Imagery is fetched per block AOI, so a subscription is per block. Once the
pipeline fetches one raster for the whole farm, a per-block subscription no
longer describes what happens: the farm is photographed either way, and the
per-block rows become a fiction that says otherwise.

This adds the farm-level row and MIGRATES the existing per-block rows into it.
The block rows are left in place and untouched — they still drive today's
ingestion, and they are the rollback. Nothing reads the new table until the
farm-AOI fetch path lands.

Cadence and cloud threshold collapse by taking the tightest value any block of
that farm asked for: a farm fetched on the fastest cadence any of its blocks
wanted cannot leave a block staler than it was, which is the only direction of
change that is safe to make automatically.

Revision ID: 0074
Revises: 0073
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "imagery_farm_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
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
        sa.Column("cadence_hours", sa.Integer(), nullable=True),
        sa.Column("cloud_cover_max_pct", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("last_successful_ingest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # One live subscription per farm and product, mirroring the partial unique
    # the per-block table carries.
    op.create_index(
        "uq_imagery_farm_subscriptions_active",
        "imagery_farm_subscriptions",
        ["farm_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND deleted_at IS NULL"),
    )

    # Collapse existing per-block intent into one row per farm and product.
    # min() on both knobs: the tightest cadence any block asked for, and the
    # strictest cloud threshold, so no block ends up worse served than it was.
    op.execute(
        """
        INSERT INTO imagery_farm_subscriptions (
            farm_id, product_id, cadence_hours, cloud_cover_max_pct,
            is_active, last_successful_ingest_at, last_attempted_at
        )
        SELECT
            b.farm_id,
            s.product_id,
            min(s.cadence_hours)               AS cadence_hours,
            min(s.cloud_cover_max_pct)         AS cloud_cover_max_pct,
            TRUE                               AS is_active,
            max(s.last_successful_ingest_at)   AS last_successful_ingest_at,
            max(s.last_attempted_at)           AS last_attempted_at
        FROM imagery_aoi_subscriptions s
        JOIN blocks b ON b.id = s.block_id
        WHERE s.is_active AND s.deleted_at IS NULL AND b.deleted_at IS NULL
        GROUP BY b.farm_id, s.product_id
        """
    )


def downgrade() -> None:
    op.drop_index("uq_imagery_farm_subscriptions_active", table_name="imagery_farm_subscriptions")
    op.drop_table("imagery_farm_subscriptions")
