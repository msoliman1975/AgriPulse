"""Geodesic polygon helpers for pivot / sector creation.

For human-scale center-pivot rigs (radii up to ~1 km) a spherical
approximation of the Earth is accurate to a fraction of a percent.
The migration's ``blocks_geom_compute`` trigger reprojects the 4326
polygon into UTM and computes ``area_m2`` server-side, so callers
need only hand over a valid Polygon ring.
"""

from __future__ import annotations

import math
from typing import Any

_EARTH_RADIUS_M = 6_378_137.0  # WGS-84 equatorial radius

# 64 vertices per full circle is the same density mapbox-gl-draw uses
# for its turf.circle helper — visually smooth without exploding row
# size or breaking PostGIS validity rules.
_DEFAULT_FULL_VERTICES = 64


def circle_polygon(
    *,
    lat: float,
    lon: float,
    radius_m: float,
    vertices: int = _DEFAULT_FULL_VERTICES,
) -> dict[str, Any]:
    """Return a GeoJSON Polygon approximating a circle on the WGS-84 sphere."""
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    if vertices < 8:
        vertices = 8

    coords: list[list[float]] = []
    cos_lat = math.cos(math.radians(lat))
    if cos_lat < 1e-6:
        # Within 0.06 degree of a pole; the projection breaks down. Pivot
        # rigs aren't installed at the poles, so make this a hard error
        # rather than silently distort.
        raise ValueError("Pivot too close to a pole to project")
    for i in range(vertices):
        theta = 2.0 * math.pi * i / vertices
        dx_m = radius_m * math.cos(theta)
        dy_m = radius_m * math.sin(theta)
        dlat = dy_m / _EARTH_RADIUS_M * 180.0 / math.pi
        dlon = dx_m / (_EARTH_RADIUS_M * cos_lat) * 180.0 / math.pi
        coords.append([lon + dlon, lat + dlat])
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


def sector_polygon(
    *,
    lat: float,
    lon: float,
    radius_m: float,
    start_deg: float,
    end_deg: float,
    arc_vertices: int | None = None,
) -> dict[str, Any]:
    """Pie-slice polygon: center → arc → center.

    ``start_deg`` and ``end_deg`` are measured counter-clockwise from
    east, matching ``circle_polygon`` so a full revolution can be
    sliced into equal wedges without offset.
    """
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    span = end_deg - start_deg
    if span <= 0:
        raise ValueError("Sector span must be positive")

    if arc_vertices is None:
        # Match the per-segment density of the full-circle approximation.
        arc_vertices = max(2, int(round(_DEFAULT_FULL_VERTICES * span / 360.0)))

    cos_lat = math.cos(math.radians(lat))
    if cos_lat < 1e-6:
        raise ValueError("Pivot too close to a pole to project")

    coords: list[list[float]] = [[lon, lat]]
    for i in range(arc_vertices + 1):
        t = start_deg + span * i / arc_vertices
        theta = math.radians(t)
        dx_m = radius_m * math.cos(theta)
        dy_m = radius_m * math.sin(theta)
        dlat = dy_m / _EARTH_RADIUS_M * 180.0 / math.pi
        dlon = dx_m / (_EARTH_RADIUS_M * cos_lat) * 180.0 / math.pi
        coords.append([lon + dlon, lat + dlat])
    coords.append([lon, lat])
    return {"type": "Polygon", "coordinates": [coords]}


def equal_sectors(
    *,
    lat: float,
    lon: float,
    radius_m: float,
    sector_count: int,
) -> list[dict[str, Any]]:
    """``sector_count`` equal-angle slices covering the full circle.

    Slice 0 starts at 0 deg east and sweeps counter-clockwise. The
    returned list is ordered by start angle so a caller pairing them
    with codes ``S1..SN`` gets a stable convention.
    """
    if sector_count < 1:
        raise ValueError("sector_count must be >= 1")
    span = 360.0 / sector_count
    return [
        sector_polygon(
            lat=lat,
            lon=lon,
            radius_m=radius_m,
            start_deg=i * span,
            end_deg=(i + 1) * span,
        )
        for i in range(sector_count)
    ]
