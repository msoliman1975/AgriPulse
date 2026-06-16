"""Grid-based auto-blocking — pure Python, no GIS libs.

The endpoint produces *candidates* the user edits or commits; this is a
preview, not a survey-grade subdivision. We deliberately keep the
algorithm dependency-free:

  * Use an equirectangular approximation centered on the farm's bbox to
    convert WGS84 ↔ meters with sub-percent error at Egyptian latitudes.
  * Generate a uniform metric grid and, for every cell, **clip the farm
    boundary to the cell rectangle** so the emitted candidate honours the
    AoI: cells fully inside the farm come out as whole rectangles, cells
    that straddle the boundary come out as the clipped (ragged-edge)
    intersection, and cells entirely outside are dropped. No block ever
    spills past the AoI.

Clipping uses Sutherland-Hodgman. That algorithm is correct only when the
*clip* window is convex, so we clip the (possibly concave) boundary ring
**against the cell rectangle** — a rectangle is always convex — which makes
it robust for any farm shape, not just convex ones.

Limitations (acceptable for a preview): polygon holes are not subtracted
(farm boundaries rarely have holes in MVP), and the per-cell ``area_m2`` is
the equirectangular shoelace area of the clipped piece — a good estimate,
but the canonical area + UTM transform are recomputed server-side by the
PostGIS triggers we own when the candidate is committed.

If we later need survey-grade clipping (holes, geodesic area), swap this
module for a shapely + pyproj implementation; the FarmService API stays the
same.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

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


def _outer_rings(geom: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Return the exterior ring of each polygon as an *open* ring.

    Holes (interior rings) are intentionally ignored — see module docstring.
    Each ring has its closing vertex stripped so the clipper treats it as a
    cycle without a duplicated point.
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


# ---- Sutherland-Hodgman clip of a ring against an axis-aligned cell -------


def _intersect_x(p: tuple[float, float], q: tuple[float, float], cx: float) -> tuple[float, float]:
    t = (cx - p[0]) / (q[0] - p[0])
    return (cx, p[1] + t * (q[1] - p[1]))


def _intersect_y(p: tuple[float, float], q: tuple[float, float], cy: float) -> tuple[float, float]:
    t = (cy - p[1]) / (q[1] - p[1])
    return (p[0] + t * (q[0] - p[0]), cy)


def _clip_axis(
    poly: list[tuple[float, float]],
    *,
    axis: int,
    bound: float,
    keep_ge: bool,
) -> list[tuple[float, float]]:
    """Clip an open ring against a single half-plane of the cell rectangle.

    ``axis`` 0 = vertical line x=bound, 1 = horizontal line y=bound.
    ``keep_ge`` keeps the side where coordinate >= bound (else <= bound).
    """
    if not poly:
        return []
    out: list[tuple[float, float]] = []
    intersect = _intersect_x if axis == 0 else _intersect_y
    n = len(poly)
    for i in range(n):
        cur = poly[i]
        prv = poly[i - 1]
        cur_in = (cur[axis] >= bound) if keep_ge else (cur[axis] <= bound)
        prv_in = (prv[axis] >= bound) if keep_ge else (prv[axis] <= bound)
        if cur_in:
            if not prv_in:
                out.append(intersect(prv, cur, bound))
            out.append(cur)
        elif prv_in:
            out.append(intersect(prv, cur, bound))
    return out


def _clip_ring_to_cell(
    ring: list[tuple[float, float]],
    *,
    left: float,
    bottom: float,
    right: float,
    top: float,
) -> list[tuple[float, float]]:
    """Return the portion of ``ring`` inside the cell rectangle (open ring)."""
    clipped = _clip_axis(ring, axis=0, bound=left, keep_ge=True)
    clipped = _clip_axis(clipped, axis=0, bound=right, keep_ge=False)
    clipped = _clip_axis(clipped, axis=1, bound=bottom, keep_ge=True)
    clipped = _clip_axis(clipped, axis=1, bound=top, keep_ge=False)
    return clipped


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


def auto_grid_candidates(
    boundary_geojson: dict[str, Any],
    *,
    cell_size_m: int,
) -> list[dict[str, Any]]:
    """Generate candidate Polygon GeoJSONs that tile the farm, clipped to AoI.

    Each returned dict:
        {"code": "AG-R03-C07", "geometry": {<Polygon>}, "area_m2": Decimal}

    The geometry is the intersection of the grid cell with the farm boundary,
    so candidates never spill past the AoI. ``area_m2`` is the (approximate)
    area of that clipped piece; PostGIS recomputes the canonical value on
    commit.
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

            # Clip the farm boundary to this cell. A cell may intersect more
            # than one polygon of a MultiPolygon farm — emit each disjoint
            # piece with a suffixed code so block codes stay unique.
            pieces: list[list[tuple[float, float]]] = []
            for ring in rings:
                clipped = _clip_ring_to_cell(
                    ring,
                    left=cell_left,
                    bottom=cell_bottom,
                    right=cell_right,
                    top=cell_top,
                )
                if len(clipped) >= 3:
                    area = _ring_area_m2(clipped, minx=minx, miny=miny, m_per_deg_lon=m_per_deg_lon)
                    if area >= min_area:
                        pieces.append(clipped)

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
