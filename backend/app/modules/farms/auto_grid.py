"""Grid-based auto-blocking.

The endpoint produces *candidates* the user edits or commits; this is a
preview, not a survey-grade subdivision. The algorithm:

  * Use an equirectangular approximation centered on the farm's bbox to
    convert WGS84 ↔ meters with sub-percent error at Egyptian latitudes.
  * Generate a uniform metric grid and, for every cell, **intersect the farm
    boundary with the cell rectangle** so the emitted candidate honours the
    AoI: cells fully inside the farm come out as whole rectangles, cells
    that straddle the boundary come out as the clipped (ragged-edge)
    intersection, and cells entirely outside are dropped. No block ever
    spills past the AoI.

Clipping is done with shapely (``Polygon.intersection``). We previously
hand-rolled a Sutherland-Hodgman clip to stay dependency-free, but that
algorithm cannot represent a *multi-component* intersection: when a single
(concave) farm ring meets one cell in two or more disjoint pieces it stitched
them into a single self-touching ring joined by zero-width bridges. Those
rings are invalid GeoJSON — they render as if they spill across the AoI and,
once committed, are stored unrepaired with a wrong ``ST_Area`` (the
``blocks_geom_compute`` trigger does not call ``ST_MakeValid``). shapely
returns a valid Polygon/MultiPolygon, so each disjoint piece is emitted as
its own candidate with a ``-P{n}`` suffix.

Limitations (acceptable for a preview): polygon holes are not subtracted
(farm boundaries rarely have holes in MVP — we build the clip subject from
the exterior rings only), and the per-cell ``area_m2`` is the
equirectangular shoelace area of the clipped piece — a good estimate, but
the canonical area + UTM transform are recomputed server-side by the PostGIS
triggers we own when the candidate is committed.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from shapely import make_valid
from shapely.geometry import Polygon as _ShapelyPolygon
from shapely.geometry import box as _shapely_box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from app.modules.farms.errors import GeometryInvalidError

_MIN_CELL_M = 10
_MAX_CELL_M = 5000

# A clipped piece smaller than this fraction of a full cell is a degenerate
# sliver along the boundary — drop it rather than emit a hairline block.
_MIN_AREA_FRACTION = 0.01

# Equirectangular metric approximation: meters per degree of lon/lat.
# 1° latitude ≈ 110_540 m (constant near sea level).
# 1° longitude ≈ 111_320 * cos(lat) m.
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON_AT_EQUATOR = 111_320.0


def _lon_meters_per_degree(lat_deg: float) -> float:
    return _M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(lat_deg))


def cell_size_for_max_area_m2(max_area_m2: float) -> int:
    """Derive the grid cell edge (m) whose square area is the per-block cap.

    A full interior cell is a ``side`` by ``side`` square and clipping only ever
    *shrinks* boundary cells, so the square's area is the maximum area any
    emitted block can have. Invert that: ``side = sqrt(max_area)``.

    The result is clamped to the supported cell-size range so a very small or
    very large target still produces a usable grid; the caller echoes the
    effective ``cell_size_m`` back to the UI so the user sees what was applied.
    """
    if max_area_m2 <= 0:
        raise GeometryInvalidError("max_area_m2 must be positive")
    side = round(math.sqrt(max_area_m2))
    return max(_MIN_CELL_M, min(_MAX_CELL_M, side))


def _outer_rings(geom: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Return the exterior ring of each polygon as an *open* ring.

    Holes (interior rings) are intentionally ignored — see module docstring.
    Each ring has its closing vertex stripped.
    """
    geom_type = geom.get("type")
    if geom_type == "Polygon":
        return [_open_ring(geom["coordinates"][0])]
    if geom_type == "MultiPolygon":
        return [_open_ring(poly[0]) for poly in geom["coordinates"] if poly]
    raise GeometryInvalidError(f"auto-grid expects Polygon or MultiPolygon, got {geom_type!r}")


def _open_ring(ring: list[Any]) -> list[tuple[float, float]]:
    pts = [(float(p[0]), float(p[1])) for p in ring]
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _bbox(rings: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for ring in rings:
        for x, y in ring:
            minx = min(minx, x)
            miny = min(miny, y)
            maxx = max(maxx, x)
            maxy = max(maxy, y)
    if not math.isfinite(minx):
        raise GeometryInvalidError("auto-grid input has no coordinates")
    return minx, miny, maxx, maxy


def _farm_geometry(rings: list[list[tuple[float, float]]]) -> BaseGeometry:
    """Build a single valid shapely geometry from the farm's exterior rings.

    A self-intersecting (bowtie) farm ring is repaired with ``make_valid`` so
    the per-cell intersection always operates on a valid subject.
    """
    polys: list[BaseGeometry] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        poly: BaseGeometry = _ShapelyPolygon(ring)
        if not poly.is_valid:
            poly = make_valid(poly)
        polys.append(poly)
    if not polys:
        raise GeometryInvalidError("auto-grid input has no rings")
    geom = polys[0] if len(polys) == 1 else unary_union(polys)
    if geom.is_empty:
        raise GeometryInvalidError("auto-grid farm geometry is empty")
    return geom


def _polygon_components(geom: BaseGeometry) -> list[_ShapelyPolygon]:
    """Flatten any intersection result into its non-empty polygon pieces."""
    geom_type = geom.geom_type
    if geom_type == "Polygon":
        return [] if geom.is_empty else [geom]
    if geom_type in ("MultiPolygon", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "Polygon" and not g.is_empty]
    return []


def _ring_area_m2(
    ring: list[tuple[float, float]],
    *,
    minx: float,
    miny: float,
    m_per_deg_lon: float,
) -> float:
    """Equirectangular shoelace area of an open ring, in m²."""
    n = len(ring)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        ax = (x1 - minx) * m_per_deg_lon
        ay = (y1 - miny) * _M_PER_DEG_LAT
        bx = (x2 - minx) * m_per_deg_lon
        by = (y2 - miny) * _M_PER_DEG_LAT
        s += ax * by - bx * ay
    return abs(s) / 2.0


def _exterior_open_ring(poly: _ShapelyPolygon) -> list[tuple[float, float]]:
    """The exterior ring of a shapely polygon as an open ring (no closing dup)."""
    coords = [(float(x), float(y)) for x, y in poly.exterior.coords]
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def auto_grid_candidates(
    boundary_geojson: dict[str, Any],
    *,
    cell_size_m: int,
) -> list[dict[str, Any]]:
    """Generate candidate Polygon GeoJSONs that tile the farm, clipped to AoI.

    Each returned dict:
        {"code": "AG-R03-C07", "geometry": {<Polygon>}, "area_m2": Decimal}

    The geometry is the intersection of the grid cell with the farm boundary,
    so candidates never spill past the AoI. A cell that meets the farm in more
    than one disjoint piece (concave farms, or a MultiPolygon AoI) emits one
    candidate per piece with a ``-P{n}`` suffix so block codes stay unique and
    every candidate is a valid, simple polygon. ``area_m2`` is the
    (approximate) area of that clipped piece; PostGIS recomputes the canonical
    value on commit.
    """
    if not (_MIN_CELL_M <= cell_size_m <= _MAX_CELL_M):
        raise GeometryInvalidError(f"cell_size_m must be between {_MIN_CELL_M} and {_MAX_CELL_M}")

    rings = _outer_rings(boundary_geojson)
    if not rings:
        raise GeometryInvalidError("auto-grid input has no rings")

    minx, miny, maxx, maxy = _bbox(rings)
    centre_lat = (miny + maxy) / 2.0
    m_per_deg_lon = _lon_meters_per_degree(centre_lat)
    if m_per_deg_lon <= 0:
        raise GeometryInvalidError("farm centroid latitude is degenerate")

    farm_geom = _farm_geometry(rings)

    cell_lon = cell_size_m / m_per_deg_lon
    cell_lat = cell_size_m / _M_PER_DEG_LAT

    n_cols = max(1, math.ceil((maxx - minx) / cell_lon))
    n_rows = max(1, math.ceil((maxy - miny) / cell_lat))

    min_area = _MIN_AREA_FRACTION * cell_size_m * cell_size_m

    candidates: list[dict[str, Any]] = []
    for row in range(n_rows):
        cell_bottom = miny + row * cell_lat
        cell_top = cell_bottom + cell_lat
        for col in range(n_cols):
            cell_left = minx + col * cell_lon
            cell_right = cell_left + cell_lon

            # Intersect the farm with this cell. The result may be a single
            # polygon, several disjoint polygons (concave AoI or MultiPolygon),
            # or empty — emit each disjoint piece as its own candidate.
            clipped = farm_geom.intersection(
                _shapely_box(cell_left, cell_bottom, cell_right, cell_top)
            )

            pieces: list[list[tuple[float, float]]] = []
            for component in _polygon_components(clipped):
                ring = _exterior_open_ring(component)
                if len(ring) < 3:
                    continue
                area = _ring_area_m2(ring, minx=minx, miny=miny, m_per_deg_lon=m_per_deg_lon)
                if area >= min_area:
                    pieces.append(ring)

            for piece_idx, piece in enumerate(pieces):
                area = _ring_area_m2(piece, minx=minx, miny=miny, m_per_deg_lon=m_per_deg_lon)
                # Close the ring for GeoJSON output.
                coords = [list(p) for p in piece]
                coords.append(list(piece[0]))
                geometry = {"type": "Polygon", "coordinates": [coords]}
                code = f"AG-R{row + 1:02d}-C{col + 1:02d}"
                if len(pieces) > 1:
                    code = f"{code}-P{piece_idx + 1}"
                candidates.append(
                    {
                        "code": code,
                        "geometry": geometry,
                        "area_m2": Decimal(f"{area:.2f}"),
                    }
                )
    return candidates
