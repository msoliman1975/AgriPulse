"""farms.aoi_hash + farm_scene_rasters — farm-wide imagery assets.

Imagery is fetched, stored and computed per BLOCK AOI today: a 36-block farm
produces 36 rasters per scene, land between the blocks has no pixels at all,
and adjacent blocks share a boundary pixel that gets written into both files.
The fix is one raster per farm, which needs the same stable identity blocks
already have — the asset key is
``{provider}/{product}/{scene}/{aoi_hash}/{index}.tif``.

Deliberately the SAME formula as ``blocks_geom_compute``: sha256 over the WKT
of the UTM boundary. Reshaping a farm therefore moves its rasters to a new
prefix rather than silently overwriting imagery of a different footprint,
which is exactly the property that keeps a reshaped BLOCK from serving stale
pixels today.

Revision ID: 0073
Revises: 0072
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


# ST_Multi is in the farms trigger because farms carry MultiPolygon; the hash
# input is the same WKT-of-UTM-geometry the blocks trigger uses.
_FARMS_GEOM_FN_WITH_HASH = """
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
    NEW.aoi_hash := encode(
        digest(ST_AsText(NEW.boundary_utm), 'sha256'),
        'hex'
    );
    RETURN NEW;
END;
$$;
"""

_FARMS_GEOM_FN_ORIGINAL = """
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


def upgrade() -> None:
    # Nullable so the column can land before the backfill; every row is filled
    # below and the trigger keeps it filled from here on. Left nullable rather
    # than NOT NULL because a farm row is inserted with a placeholder boundary
    # in the same pattern blocks use, and the trigger fires BEFORE INSERT.
    op.add_column("farms", sa.Column("aoi_hash", sa.Text(), nullable=True))
    op.execute(_FARMS_GEOM_FN_WITH_HASH)
    # Backfill existing farms through the same expression, so a farm created
    # before this migration hashes identically to one created after it.
    op.execute(
        """
        UPDATE farms
           SET aoi_hash = encode(digest(ST_AsText(boundary_utm), 'sha256'), 'hex')
         WHERE boundary_utm IS NOT NULL
        """
    )

    # What has actually been stitched, so the API can answer "is there a farm
    # raster for this pass?" without a bucket probe per request — and so the
    # cutover can be per farm: a farm with rows here serves one raster, a farm
    # without keeps the per-block path untouched.
    op.create_table(
        "farm_scene_rasters",
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
        # Cross-schema logical reference to public.imagery_products — never a
        # real FK, per the no-tenant-to-public rule.
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        # `provider/product/scene/aoi` — the same shape imagery_ingestion_jobs
        # carries, so a caller appends `/{index}.tif` without knowing whether
        # it is holding a block asset or a farm one.
        sa.Column("stac_item_id", sa.Text(), nullable=False),
        # The farm boundary this was cut against. A reshape changes it, which
        # is what stops a resized farm from serving rasters of its old shape.
        sa.Column("aoi_hash", sa.Text(), nullable=False),
        sa.Column("blocks_merged", sa.Integer(), nullable=False),
        sa.Column("indices", postgresql.JSONB(), nullable=False),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # One raster per farm, pass and boundary. Rebuilding a pass replaces the
    # row rather than accumulating history nobody reads.
    op.create_unique_constraint(
        "uq_farm_scene_rasters_farm_scene_aoi",
        "farm_scene_rasters",
        ["farm_id", "scene_datetime", "aoi_hash"],
    )
    op.create_index(
        "ix_farm_scene_rasters_farm_scene",
        "farm_scene_rasters",
        ["farm_id", "scene_datetime"],
    )


def downgrade() -> None:
    op.drop_index("ix_farm_scene_rasters_farm_scene", table_name="farm_scene_rasters")
    op.drop_constraint("uq_farm_scene_rasters_farm_scene_aoi", "farm_scene_rasters")
    op.drop_table("farm_scene_rasters")
    op.execute(_FARMS_GEOM_FN_ORIGINAL)
    op.drop_column("farms", "aoi_hash")
