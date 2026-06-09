"""Sub-block grid zones (fishnet) foundation.

Adds three tables to the per-tenant schema:

  1. ``grid_configs`` — one active row per (block, imagery product).
     Carries the cell size in metres + the UTM SRID the grid was
     materialised in. Soft-retired via ``retired_at`` so historical
     observations remain interpretable after a rezone.

  2. ``grid_cells`` — the materialised polygons. Generated once per
     ``grid_config`` by snapping to the UTM SRID's natural origin
     (0, 0) so neighbouring blocks in the same zone, at the same cell
     size, get perfectly aligned cells.

  3. ``block_grid_aggregates`` — TimescaleDB hypertable mirroring
     ``block_index_aggregates`` but one row per cell instead of per
     block. The UNIQUE on (time, cell_id, index_code, product_id) is
     the idempotency key; re-running compute for the same scene is a
     no-op.

Cells reference grid_config via FK; observations reference cell_id
without an FK (hypertables can't carry one), but the application
guarantees referential integrity at write time. Soft-retired configs
keep their cells and observations as history.

Revision ID: 0034
Revises: 0033
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2.types import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | Sequence[str] | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- grid_configs --------------------------------------------------
    op.create_table(
        "grid_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Cross-schema logical FK to public.imagery_products.id (same
        # pattern as imagery_aoi_subscriptions.product_id).
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cell_size_m", sa.Numeric(6, 2), nullable=False),
        # The UTM SRID the cells are materialised in. Defaults to
        # blocks.boundary_utm's SRID (32636 in this deployment) but
        # stored explicitly so a future multi-zone deployment doesn't
        # need a migration.
        sa.Column("utm_srid", sa.Integer(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name="fk_grid_configs_block_id_blocks",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cell_size_m > 0",
            name="ck_grid_configs_cell_size_positive",
        ),
    )
    # Only one *active* (non-retired) config per (block, product). Old
    # configs with `retired_at` set remain in the table as history.
    op.create_index(
        "uq_grid_configs_block_product_active",
        "grid_configs",
        ["block_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_grid_configs_updated_at "
        "BEFORE UPDATE ON grid_configs "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- grid_cells ----------------------------------------------------
    # Cells carry their geometry in the config's UTM SRID for cheap area
    # math and pixel-grid alignment; centroid in 4326 for display.
    op.create_table(
        "grid_cells",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("grid_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_idx", sa.Integer(), nullable=False),
        sa.Column("col_idx", sa.Integer(), nullable=False),
        # SRID-agnostic POLYGON — the parent grid_config's utm_srid is
        # the source of truth at insertion time. Keeps the schema open
        # to a future multi-UTM-zone deployment without an ALTER TYPE.
        sa.Column(
            "geom",
            Geometry(geometry_type="POLYGON", spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "centroid",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["grid_config_id"],
            ["grid_configs.id"],
            name="fk_grid_cells_grid_config_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "grid_config_id",
            "row_idx",
            "col_idx",
            name="uq_grid_cells_grid_config_row_col",
        ),
        sa.CheckConstraint("area_m2 > 0", name="ck_grid_cells_area_positive"),
    )
    op.execute("CREATE INDEX ix_grid_cells_geom_gist ON grid_cells USING GIST (geom)")
    op.execute("CREATE INDEX ix_grid_cells_grid_config_id ON grid_cells (grid_config_id)")

    # ---- block_grid_aggregates (hypertable) ----------------------------
    # No PK column: hypertables need the time column in any unique
    # constraint, AND the space-partitioning column (block_id) must be
    # part of every UNIQUE/PK on the table. The UNIQUE on
    # (time, block_id, cell_id, index_code, product_id) is the
    # idempotency key — adding block_id is redundant for logical
    # uniqueness (cell_id is globally unique) but mandatory for the
    # hypertable to be created.
    op.create_table(
        "block_grid_aggregates",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cell_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("index_code", sa.Text(), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mean", sa.Numeric(7, 4), nullable=True),
        sa.Column("min", sa.Numeric(7, 4), nullable=True),
        sa.Column("max", sa.Numeric(7, 4), nullable=True),
        sa.Column("std_dev", sa.Numeric(7, 4), nullable=True),
        sa.Column("valid_pixel_count", sa.Integer(), nullable=False),
        sa.Column("total_pixel_count", sa.Integer(), nullable=False),
        sa.Column(
            "valid_pixel_pct",
            sa.Numeric(5, 2),
            sa.Computed(
                "100.0 * valid_pixel_count / NULLIF(total_pixel_count, 0)",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("cloud_cover_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("stac_item_id", sa.Text(), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "time",
            "block_id",
            "cell_id",
            "index_code",
            "product_id",
            name="uq_block_grid_aggregates_time_block_cell_index_product",
        ),
        sa.CheckConstraint(
            "total_pixel_count >= 0 AND valid_pixel_count >= 0 "
            "AND valid_pixel_count <= total_pixel_count",
            name="ck_block_grid_aggregates_pixel_counts",
        ),
    )
    # Hypertable: time partition + block_id space partition. Mirrors
    # block_index_aggregates so chunks align across the two tables and
    # joins on (block_id, time) hit overlapping chunk windows.
    op.execute(
        """
        SELECT create_hypertable(
            'block_grid_aggregates',
            'time',
            partitioning_column => 'block_id',
            number_partitions => 4,
            chunk_time_interval => INTERVAL '7 days',
            if_not_exists => TRUE
        )
        """
    )
    op.execute(
        """
        ALTER TABLE block_grid_aggregates SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'block_id, index_code'
        )
        """
    )
    op.execute(
        "SELECT add_compression_policy("
        "'block_grid_aggregates', INTERVAL '30 days', if_not_exists => TRUE)"
    )

    op.create_index(
        "ix_block_grid_aggregates_block_time_index",
        "block_grid_aggregates",
        ["block_id", sa.text("time DESC"), "index_code"],
    )
    op.create_index(
        "ix_block_grid_aggregates_cell_time_index",
        "block_grid_aggregates",
        ["cell_id", sa.text("time DESC"), "index_code"],
    )


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy(" "'block_grid_aggregates', if_exists => TRUE)")
    op.drop_index(
        "ix_block_grid_aggregates_cell_time_index",
        table_name="block_grid_aggregates",
    )
    op.drop_index(
        "ix_block_grid_aggregates_block_time_index",
        table_name="block_grid_aggregates",
    )
    op.drop_table("block_grid_aggregates")

    op.execute("DROP INDEX IF EXISTS ix_grid_cells_grid_config_id")
    op.execute("DROP INDEX IF EXISTS ix_grid_cells_geom_gist")
    op.drop_table("grid_cells")

    op.execute("DROP TRIGGER IF EXISTS trg_grid_configs_updated_at ON grid_configs")
    op.drop_index(
        "uq_grid_configs_block_product_active",
        table_name="grid_configs",
    )
    op.drop_table("grid_configs")
