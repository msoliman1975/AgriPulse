"""farms, blocks, block_crops, farm_attachments, block_attachments + triggers.

Per data_model § 5.4 / § 5.5 / § 5.6 / § 5.7. All tables live in the
per-tenant schema; this migration is applied once per tenant by the
runner in scripts/migrate_tenants.py (and on tenant creation by
tenancy.bootstrap).

Triggers populate computed columns from the WGS84 boundary:

  * boundary_utm  := ST_Transform(boundary, 32636)
  * centroid      := ST_Centroid(boundary)
  * area_m2       := ST_Area(boundary_utm)         [accurate on UTM]
  * aoi_hash      := SHA-256(ST_AsText(boundary_utm))   [blocks only]

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2.types import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Trigger functions live in the per-tenant schema (the search_path is set
# to that schema by env.py), so functions resolve unambiguously when the
# trigger runs against rows of the same schema.

_FARMS_GEOM_FN = """
CREATE OR REPLACE FUNCTION farms_geom_compute()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.boundary IS NULL THEN
        RAISE EXCEPTION 'farms.boundary cannot be NULL';
    END IF;
    NEW.boundary_utm := ST_Multi(ST_Transform(NEW.boundary, 32636));
    NEW.centroid := ST_Centroid(NEW.boundary);
    NEW.area_m2 := ST_Area(NEW.boundary_utm);
    RETURN NEW;
END;
$$;
"""

_BLOCKS_GEOM_FN = """
CREATE OR REPLACE FUNCTION blocks_geom_compute()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.boundary IS NULL THEN
        RAISE EXCEPTION 'blocks.boundary cannot be NULL';
    END IF;
    NEW.boundary_utm := ST_Transform(NEW.boundary, 32636);
    NEW.centroid := ST_Centroid(NEW.boundary);
    NEW.area_m2 := ST_Area(NEW.boundary_utm);
    NEW.aoi_hash := encode(
        digest(ST_AsText(NEW.boundary_utm), 'sha256'),
        'hex'
    );
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    # ---- farms ----------------------------------------------------------
    op.create_table(
        "farms",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "boundary",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "boundary_utm",
            Geometry(geometry_type="MULTIPOLYGON", srid=32636, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "centroid",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Numeric(14, 2), nullable=False),
        sa.Column("elevation_m", sa.Numeric(7, 2), nullable=True),
        sa.Column("governorate", sa.Text(), nullable=True),
        sa.Column("district", sa.Text(), nullable=True),
        sa.Column("nearest_city", sa.Text(), nullable=True),
        sa.Column("address_line", sa.Text(), nullable=True),
        sa.Column(
            "farm_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'commercial'"),
        ),
        sa.Column("ownership_type", sa.Text(), nullable=True),
        sa.Column("primary_water_source", sa.Text(), nullable=True),
        sa.Column("established_date", sa.Date(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
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
        sa.CheckConstraint(
            "farm_type IN ('commercial','research','contract')",
            name="ck_farms_farm_type",
        ),
        sa.CheckConstraint(
            "ownership_type IS NULL OR ownership_type IN "
            "('owned','leased','partnership','other')",
            name="ck_farms_ownership_type",
        ),
        sa.CheckConstraint(
            "primary_water_source IS NULL OR primary_water_source IN "
            "('well','canal','nile','desalinated','rainfed','mixed')",
            name="ck_farms_primary_water_source",
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="ck_farms_status",
        ),
    )
    op.create_index(
        "uq_farms_code_active",
        "farms",
        ["code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_farms_boundary",
        "farms",
        ["boundary"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_farms_centroid",
        "farms",
        ["centroid"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_farms_status_active",
        "farms",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_farms_governorate_active",
        "farms",
        ["governorate"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(_FARMS_GEOM_FN)
    op.execute(
        "CREATE TRIGGER trg_farms_geom_compute "
        "BEFORE INSERT OR UPDATE OF boundary ON farms "
        "FOR EACH ROW EXECUTE FUNCTION farms_geom_compute()"
    )
    op.execute(
        "CREATE TRIGGER trg_farms_updated_at "
        "BEFORE UPDATE ON farms "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- blocks ---------------------------------------------------------
    op.create_table(
        "blocks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "boundary",
            Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "boundary_utm",
            Geometry(geometry_type="POLYGON", srid=32636, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "centroid",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("area_m2", sa.Numeric(14, 2), nullable=False),
        sa.Column("elevation_m", sa.Numeric(7, 2), nullable=True),
        sa.Column("slope_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("aspect_deg", sa.Numeric(5, 2), nullable=True),
        sa.Column("irrigation_system", sa.Text(), nullable=True),
        sa.Column("irrigation_source", sa.Text(), nullable=True),
        sa.Column("flow_rate_m3_per_hour", sa.Numeric(8, 2), nullable=True),
        sa.Column("soil_texture", sa.Text(), nullable=True),
        sa.Column("salinity_class", sa.Text(), nullable=True),
        sa.Column("soil_ph", sa.Numeric(3, 1), nullable=True),
        sa.Column("soil_ec_ds_per_m", sa.Numeric(5, 2), nullable=True),
        sa.Column("soil_organic_matter_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("last_soil_test_date", sa.Date(), nullable=True),
        sa.Column("responsible_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("aoi_hash", sa.Text(), nullable=False),
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
            ["farm_id"],
            ["farms.id"],
            name="fk_blocks_farm_id_farms",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "irrigation_system IS NULL OR irrigation_system IN "
            "('drip','micro_sprinkler','pivot','furrow','flood','surface','none')",
            name="ck_blocks_irrigation_system",
        ),
        sa.CheckConstraint(
            "irrigation_source IS NULL OR irrigation_source IN " "('well','canal','nile','mixed')",
            name="ck_blocks_irrigation_source",
        ),
        sa.CheckConstraint(
            "soil_texture IS NULL OR soil_texture IN "
            "('sandy','sandy_loam','loam','clay_loam','clay','silty_loam','silty_clay')",
            name="ck_blocks_soil_texture",
        ),
        sa.CheckConstraint(
            "salinity_class IS NULL OR salinity_class IN "
            "('non_saline','slightly_saline','moderately_saline','strongly_saline')",
            name="ck_blocks_salinity_class",
        ),
        sa.CheckConstraint(
            "soil_ph IS NULL OR (soil_ph >= 0 AND soil_ph <= 14)",
            name="ck_blocks_soil_ph_range",
        ),
        sa.CheckConstraint(
            "status IN ('active','fallow','abandoned','under_preparation','archived')",
            name="ck_blocks_status",
        ),
    )
    op.create_index(
        "uq_blocks_farm_id_code_active",
        "blocks",
        ["farm_id", "code"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_blocks_boundary",
        "blocks",
        ["boundary"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_blocks_centroid",
        "blocks",
        ["centroid"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_blocks_status_active",
        "blocks",
        ["status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_blocks_irrigation_system_active",
        "blocks",
        ["irrigation_system"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(_BLOCKS_GEOM_FN)
    op.execute(
        "CREATE TRIGGER trg_blocks_geom_compute "
        "BEFORE INSERT OR UPDATE OF boundary ON blocks "
        "FOR EACH ROW EXECUTE FUNCTION blocks_geom_compute()"
    )
    op.execute(
        "CREATE TRIGGER trg_blocks_updated_at "
        "BEFORE UPDATE ON blocks "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- block_crops ----------------------------------------------------
    op.create_table(
        "block_crops",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crop_variety_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("season_label", sa.Text(), nullable=False),
        sa.Column("planting_date", sa.Date(), nullable=True),
        sa.Column("expected_harvest_start", sa.Date(), nullable=True),
        sa.Column("expected_harvest_end", sa.Date(), nullable=True),
        sa.Column("actual_harvest_date", sa.Date(), nullable=True),
        sa.Column("plant_density_per_ha", sa.Numeric(8, 2), nullable=True),
        sa.Column("row_spacing_m", sa.Numeric(5, 2), nullable=True),
        sa.Column("plant_spacing_m", sa.Numeric(5, 2), nullable=True),
        sa.Column("growth_stage", sa.Text(), nullable=True),
        sa.Column("growth_stage_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            name="fk_block_crops_block_id_blocks",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('planned','growing','harvesting','completed','aborted')",
            name="ck_block_crops_status",
        ),
    )
    op.create_index(
        "uq_block_crops_current",
        "block_crops",
        ["block_id"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE"),
    )
    op.create_index(
        "ix_block_crops_block_planting_desc",
        "block_crops",
        ["block_id", sa.text("planting_date DESC")],
    )
    op.create_index("ix_block_crops_crop", "block_crops", ["crop_id"])
    op.execute(
        "CREATE TRIGGER trg_block_crops_updated_at "
        "BEFORE UPDATE ON block_crops "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- farm_attachments ----------------------------------------------
    op.create_table(
        "farm_attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "geo_point",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
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
            ["farm_id"],
            ["farms.id"],
            name="fk_farm_attachments_farm_id_farms",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('photo','deed','soil_test_report','map','other')",
            name="ck_farm_attachments_kind",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_farm_attachments_size_positive",
        ),
    )
    op.create_index("ix_farm_attachments_farm_id", "farm_attachments", ["farm_id"])
    op.create_index("ix_farm_attachments_kind", "farm_attachments", ["kind"])
    op.execute(
        "CREATE TRIGGER trg_farm_attachments_updated_at "
        "BEFORE UPDATE ON farm_attachments "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- block_attachments ---------------------------------------------
    op.create_table(
        "block_attachments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("block_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "geo_point",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=True,
        ),
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
            name="fk_block_attachments_block_id_blocks",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "kind IN ('photo','deed','soil_test_report','map','other')",
            name="ck_block_attachments_kind",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_block_attachments_size_positive",
        ),
    )
    op.create_index("ix_block_attachments_block_id", "block_attachments", ["block_id"])
    op.create_index("ix_block_attachments_kind", "block_attachments", ["kind"])
    op.execute(
        "CREATE TRIGGER trg_block_attachments_updated_at "
        "BEFORE UPDATE ON block_attachments "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_block_attachments_updated_at ON block_attachments")
    op.drop_index("ix_block_attachments_kind", table_name="block_attachments")
    op.drop_index("ix_block_attachments_block_id", table_name="block_attachments")
    op.drop_table("block_attachments")

    op.execute("DROP TRIGGER IF EXISTS trg_farm_attachments_updated_at ON farm_attachments")
    op.drop_index("ix_farm_attachments_kind", table_name="farm_attachments")
    op.drop_index("ix_farm_attachments_farm_id", table_name="farm_attachments")
    op.drop_table("farm_attachments")

    op.execute("DROP TRIGGER IF EXISTS trg_block_crops_updated_at ON block_crops")
    op.drop_index("ix_block_crops_crop", table_name="block_crops")
    op.drop_index("ix_block_crops_block_planting_desc", table_name="block_crops")
    op.drop_index("uq_block_crops_current", table_name="block_crops")
    op.drop_table("block_crops")

    op.execute("DROP TRIGGER IF EXISTS trg_blocks_updated_at ON blocks")
    op.execute("DROP TRIGGER IF EXISTS trg_blocks_geom_compute ON blocks")
    op.execute("DROP FUNCTION IF EXISTS blocks_geom_compute()")
    op.drop_index("ix_blocks_irrigation_system_active", table_name="blocks")
    op.drop_index("ix_blocks_status_active", table_name="blocks")
    op.drop_index("ix_blocks_centroid", table_name="blocks")
    op.drop_index("ix_blocks_boundary", table_name="blocks")
    op.drop_index("uq_blocks_farm_id_code_active", table_name="blocks")
    op.drop_table("blocks")

    op.execute("DROP TRIGGER IF EXISTS trg_farms_updated_at ON farms")
    op.execute("DROP TRIGGER IF EXISTS trg_farms_geom_compute ON farms")
    op.execute("DROP FUNCTION IF EXISTS farms_geom_compute()")
    op.drop_index("ix_farms_governorate_active", table_name="farms")
    op.drop_index("ix_farms_status_active", table_name="farms")
    op.drop_index("ix_farms_centroid", table_name="farms")
    op.drop_index("ix_farms_boundary", table_name="farms")
    op.drop_index("uq_farms_code_active", table_name="farms")
    op.drop_table("farms")
