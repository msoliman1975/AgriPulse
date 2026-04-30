"""Grid-based auto-blocking — pure Python, no GIS libs.

The endpoint produces *candidates* the user edits or commits; this is a
preview, not a survey-grade subdivision. We deliberately keep the
algorithm dependency-free:

  * Use an equirectangular approximation centered on the farm's bbox to
    convert WGS84 ↔ meters with sub-percent error at Egyptian latitudes.
  * Generate a uniform metric grid and emit cells whose center sits
    inside the boundary (ray-cast test). Candidates that cross the
    boundary are NOT clipped here — the user trims them in the UI; the
    canonical area + UTM transform on commit happens server-side via
    the PostGIS triggers we own.

If we later need precise clipping, swap this module for a shapely +
pyproj implementation; the FarmService API stays the same.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from app.modules.farms.errors import GeometryInvalidError

_MIN_CELL_M = 10
_MAX_CELL_M = 5000

# Equirectangular metric approximation: meters per degree of lon/lat.
# 1° latitude ≈ 110_540 m (constant near sea level).
# 1° longitude ≈ 111_320 * cos(lat) m.
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON_AT_EQUATOR = 111_320.0


def _lon_meters_per_degree(lat_deg: float) -> float:
    return _M_PER_DEG_LON_AT_EQUATOR * math.cos(math.radians(lat_deg))


def _polygon_rings(geom: dict[str, Any]) -> list[list[tuple[float, float]]]:
    geom_type = geom.get("type")
    if geom_type == "Polygon":
        coords = geom["coordinates"]
        return [_to_ring(r) for r in coords]
    if geom_type == "MultiPolygon":
        rings: list[list[tuple[float, float]]] = []
        for poly in geom["coordinates"]:
            for r in poly:
                rings.append(_to_ring(r))
        return rings
    raise GeometryInvalidError(f"auto-grid expects Polygon or MultiPolygon, got {geom_type!r}")


def _to_ring(ring: list[Any]) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in ring]


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


def _point_in_polygon(px: float, py: float, rings: list[list[tuple[float, float]]]) -> bool:
    """Even-odd ray-cast test against all rings.

    For a Polygon: ring 0 is the outer; subsequent rings are holes. For
    our auto-grid, the farm boundary in MVP rarely has holes, but the
    parity check below handles holes correctly: a point inside the
    outer ring AND inside a hole counts as outside.
    """
    inside = False
    for ring in rings:
        if _point_in_ring(px, py, ring):
            inside = not inside
    return inside


def _point_in_ring(px: float, py: float, ring: list[tuple[float, float]]) -> bool:
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def auto_grid_candidates(
    boundary_geojson: dict[str, Any],
    *,
    cell_size_m: int,
) -> list[dict[str, Any]]:
    """Generate candidate Polygon GeoJSONs that tile the farm.

    Each returned dict:
        {"code": "AG-R03-C07", "geometry": {<Polygon>}, "area_m2": Decimal}
    """
    if not (_MIN_CELL_M <= cell_size_m <= _MAX_CELL_M):
        raise GeometryInvalidError(f"cell_size_m must be between {_MIN_CELL_M} and {_MAX_CELL_M}")

    rings = _polygon_rings(boundary_geojson)
    if not rings:
        raise GeometryInvalidError("auto-grid input has no rings")

    minx, miny, maxx, maxy = _bbox(rings)
    centre_lat = (miny + maxy) / 2.0
    m_per_deg_lon = _lon_meters_per_degree(centre_lat)
    if m_per_deg_lon <= 0:
        raise GeometryInvalidError("farm centroid latitude is degenerate")

    cell_lon = cell_size_m / m_per_deg_lon
    cell_lat = cell_size_m / _M_PER_DEG_LAT

    n_cols = max(1, math.ceil((maxx - minx) / cell_lon))
    n_rows = max(1, math.ceil((maxy - miny) / cell_lat))

    candidates: list[dict[str, Any]] = []
    for row in range(n_rows):
        cell_bottom = miny + row * cell_lat
        cell_top = cell_bottom + cell_lat
        for col in range(n_cols):
            cell_left = minx + col * cell_lon
            cell_right = cell_left + cell_lon

            # Inclusion test: cell center inside the polygon, OR any of the
            # four corners inside. Captures cells that overlap the boundary.
            cx = (cell_left + cell_right) / 2.0
            cy = (cell_bottom + cell_top) / 2.0
            if not (
                _point_in_polygon(cx, cy, rings)
                or _point_in_polygon(cell_left, cell_bottom, rings)
                or _point_in_polygon(cell_right, cell_bottom, rings)
                or _point_in_polygon(cell_right, cell_top, rings)
                or _point_in_polygon(cell_left, cell_top, rings)
            ):
                continue

            geometry = {
                "type": "Polygon",
                "coordinates": [
                    [
                        [cell_left, cell_bottom],
                        [cell_right, cell_bottom],
                        [cell_right, cell_top],
                        [cell_left, cell_top],
                        [cell_left, cell_bottom],
                    ]
                ],
            }
            # Approximate area in m² — the canonical area is recomputed
            # by PostGIS triggers when the candidate is committed.
            area_m2 = Decimal(f"{cell_size_m * cell_size_m:.2f}")
            candidates.append(
                {
                    "code": f"AG-R{row + 1:02d}-C{col + 1:02d}",
                    "geometry": geometry,
                    "area_m2": area_m2,
                }
            )
    return candidates
