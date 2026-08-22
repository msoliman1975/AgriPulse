"""farms.utm_srid — the metric coordinate system a farm's geometry lives in.

Until now every boundary was transformed to UTM zone 36 North (EPSG:32636) by
a literal inside two trigger functions. Zone 36 is right for Egypt and wrong
everywhere else, and ``ST_Transform`` does not fail outside a zone — it
returns a finite, wrong number. Measured against a local equal-area
projection, a 0.01-degree square comes out 4.8% too large in Riyadh, 13.4% too
large in Dubai, and 5.3 times too large in Sao Paulo. That number is
``area_m2``, which feeds the feddan and hectare display, the grid cell size
derived from a maximum block area, and every per-hectare figure in plans and
reports.

The zone is now a column on ``farms``. It is derived once, on insert, from the
centroid of the boundary, and never recomputed. Deriving it on every write
would be worse than the literal: an existing Egyptian farm at longitude 27
sits in zone 35, so its next edit would move it out of zone 36, change
``ST_AsText(boundary_utm)``, and therefore change ``aoi_hash`` — which is how
a farm and its blocks are matched to their stored satellite imagery. Every
farm that exists when this migration runs is backfilled with the SRID it
already has, so no ``boundary_utm``, ``area_m2`` or ``aoi_hash`` value moves.

Blocks take their farm's zone rather than deriving their own. A farm and its
blocks must share one coordinate system: the grid, the farm raster and the
per-block rasters are all cut against each other.

Re-zoning the Egyptian farms west of longitude 30 is deliberately NOT done
here. It is correct, and it needs an imagery backfill to go with it.

The zone rule is written out in full in both trigger functions rather than
factored into a helper. A trigger function resolves unqualified names through
the search_path in force when it fires, and callers write schema-qualified SQL
(``INSERT INTO "tenant_x".farms ...``) without putting that schema on the path.
A helper in the tenant schema is invisible to those callers, and the insert
dies with "function does not exist". The PostGIS and pgcrypto calls below are
safe because those extensions live in ``public``, which is always on the path.

Revision ID: 0082
Revises: 0081
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0082"
down_revision: str | Sequence[str] | None = "0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# `NEW.boundary` is SRID 4326 by column type, so a longitude reads straight off
# its centroid with no transform. 60 zones of 6 degrees, numbered from the
# antimeridian; longitude 180 exactly would compute zone 61, so it is clamped.
_FARMS_GEOM_FN_ZONED = """
CREATE OR REPLACE FUNCTION farms_geom_compute()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    c        geometry;
    lon      DOUBLE PRECISION;
    lat      DOUBLE PRECISION;
    zone_no  INTEGER;
BEGIN
    IF NEW.boundary IS NULL THEN
        RAISE EXCEPTION 'farms.boundary cannot be NULL';
    END IF;
    -- Derived once. On UPDATE the column already carries the farm's zone, so
    -- reshaping a farm never moves it between coordinate systems.
    IF NEW.utm_srid IS NULL THEN
        c := ST_Centroid(NEW.boundary);
        lon := ST_X(c);
        lat := ST_Y(c);
        zone_no := floor((lon + 180.0) / 6.0)::INTEGER + 1;
        IF zone_no < 1 THEN
            zone_no := 1;
        ELSIF zone_no > 60 THEN
            zone_no := 60;
        END IF;
        IF lat >= 0 THEN
            NEW.utm_srid := 32600 + zone_no;
        ELSE
            NEW.utm_srid := 32700 + zone_no;
        END IF;
    END IF;
    NEW.boundary_utm := ST_Multi(ST_Transform(NEW.boundary, NEW.utm_srid));
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

_BLOCKS_GEOM_FN_ZONED = """
CREATE OR REPLACE FUNCTION blocks_geom_compute()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    farm_srid INTEGER;
    c         geometry;
    lon       DOUBLE PRECISION;
    lat       DOUBLE PRECISION;
    zone_no   INTEGER;
BEGIN
    IF NEW.boundary IS NULL THEN
        RAISE EXCEPTION 'blocks.boundary cannot be NULL';
    END IF;
    -- Qualified by the trigger's own schema, not left to the search_path.
    -- Callers insert schema-qualified (`INSERT INTO "tenant_x".blocks ...`)
    -- without putting that schema on the path, and a bare `FROM farms` then
    -- fails with "relation does not exist". `format('%I', ...)` is safe: the
    -- value comes from the trigger context, not from the row.
    EXECUTE format('SELECT utm_srid FROM %I.farms WHERE id = $1', TG_TABLE_SCHEMA)
       INTO farm_srid
      USING NEW.farm_id;
    IF farm_srid IS NULL THEN
        -- No farm row for this farm_id. The foreign key rejects the row a
        -- moment from now, so raising here would only replace that error with
        -- a less useful one, and would hide any other constraint the row also
        -- breaks. Fall back to the block's own centroid, by the same rule
        -- farms_geom_compute uses above.
        c := ST_Centroid(NEW.boundary);
        lon := ST_X(c);
        lat := ST_Y(c);
        zone_no := floor((lon + 180.0) / 6.0)::INTEGER + 1;
        IF zone_no < 1 THEN
            zone_no := 1;
        ELSIF zone_no > 60 THEN
            zone_no := 60;
        END IF;
        IF lat >= 0 THEN
            farm_srid := 32600 + zone_no;
        ELSE
            farm_srid := 32700 + zone_no;
        END IF;
    END IF;
    NEW.boundary_utm := ST_Transform(NEW.boundary, farm_srid);
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

# ---- the pre-0082 shapes, for downgrade ---------------------------------

_FARMS_GEOM_FN_0073 = """
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

_BLOCKS_GEOM_FN_0002 = """
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
    # Nullable first so the column can land before the backfill. The trigger
    # fills it on every insert from here on, so it ends NOT NULL.
    op.add_column("farms", sa.Column("utm_srid", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE farms
           SET utm_srid = ST_SRID(boundary_utm)
         WHERE boundary_utm IS NOT NULL
        """
    )
    # A farm with no metric boundary cannot exist (the column is NOT NULL),
    # but the fallback keeps the SET NOT NULL below from depending on that.
    op.execute("UPDATE farms SET utm_srid = 32636 WHERE utm_srid IS NULL")
    op.alter_column("farms", "utm_srid", nullable=False)

    # Drop the SRID from the column type. `geometry(MultiPolygon)` still pins
    # the geometry type and accepts any SRID; `geometry(MultiPolygon, 32636)`
    # rejects every other zone. Neither column carries a spatial index, so
    # there is nothing to rebuild.
    op.execute(
        "ALTER TABLE farms "
        "ALTER COLUMN boundary_utm TYPE geometry(MultiPolygon) USING boundary_utm"
    )
    op.execute(
        "ALTER TABLE blocks ALTER COLUMN boundary_utm TYPE geometry(Polygon) USING boundary_utm"
    )

    # Both functions in one migration on purpose. Replacing only one would
    # give a farm and its blocks two different coordinate systems.
    op.execute(_FARMS_GEOM_FN_ZONED)
    op.execute(_BLOCKS_GEOM_FN_ZONED)


def downgrade() -> None:
    op.execute(_FARMS_GEOM_FN_0073)
    op.execute(_BLOCKS_GEOM_FN_0002)

    # Re-narrowing the type needs every row back in zone 36. For a farm
    # outside zone 36 this rewrites boundary_utm, area_m2 and aoi_hash, so its
    # stored imagery is orphaned. That is the cost of going back, and it is
    # why this migration is one-way in practice. The restored triggers do the
    # recompute; the UPDATE only has to touch the row.
    op.execute(
        """
        UPDATE farms
           SET boundary_utm = ST_Multi(ST_Transform(boundary, 32636))
         WHERE ST_SRID(boundary_utm) <> 32636
        """
    )
    op.execute(
        """
        UPDATE blocks
           SET boundary_utm = ST_Transform(boundary, 32636)
         WHERE ST_SRID(boundary_utm) <> 32636
        """
    )
    op.execute(
        "ALTER TABLE blocks "
        "ALTER COLUMN boundary_utm TYPE geometry(Polygon, 32636) USING boundary_utm"
    )
    op.execute(
        "ALTER TABLE farms "
        "ALTER COLUMN boundary_utm TYPE geometry(MultiPolygon, 32636) USING boundary_utm"
    )
    op.drop_column("farms", "utm_srid")
