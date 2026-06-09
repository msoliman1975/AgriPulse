"""Derive a pivot-relative (ring, sector) label for a grid cell.

We keep the *square* fishnet for pivots (uniform cell area keeps the
spatial-anomaly stats clean — see ``anomaly.py``), but a square
``row/col`` index means nothing to someone standing at a center pivot.
This module translates a cell's centroid into the language of the
machine: which concentric **ring** out from the center, and which angular
**sector** (aligned to the pivot's own irrigation ``sector_count``).

Pure functions, no I/O. The projection is a local equirectangular
approximation around the pivot center — sub-percent error at pivot
scales (radii of a few hundred metres), and we only need it to bucket a
point into a ring + sector, not for survey-grade distance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_METERS_PER_DEG_LAT = 110_540.0
_METERS_PER_DEG_LON_EQUATOR = 111_320.0

# Compass labels for the common pivot sector counts. Sector 0 is centered
# on north and they advance clockwise. Any other count falls back to a
# 1-based "S<n>" label.
_COMPASS = {
    4: ("N", "E", "S", "W"),
    8: ("N", "NE", "E", "SE", "S", "SW", "W", "NW"),
}


@dataclass(frozen=True, slots=True)
class RingSector:
    ring: int  # 1-based, 1 = innermost
    sector_idx: int  # 0-based, 0 = centered on north, clockwise
    sector_label: str


def ring_sector(
    *,
    centroid_lon: float,
    centroid_lat: float,
    center_lon: float,
    center_lat: float,
    ring_width_m: float,
    sector_count: int,
) -> RingSector:
    """Bucket a cell centroid into a (ring, sector) relative to the pivot.

    ``ring_width_m`` is normally the grid's cell size, so ring N is
    roughly N cells out from the center. ``sector_count`` is the pivot's
    own irrigation sector count, so sector labels line up with how the
    machine is operated.
    """
    sectors = max(1, int(sector_count))
    dx = (
        (centroid_lon - center_lon)
        * _METERS_PER_DEG_LON_EQUATOR
        * math.cos(math.radians(center_lat))
    )
    dy = (centroid_lat - center_lat) * _METERS_PER_DEG_LAT
    radius = math.hypot(dx, dy)

    width = ring_width_m if ring_width_m > 0 else 1.0
    ring = int(radius // width) + 1  # 1-based; center cell is ring 1

    # Bearing clockwise from north, in [0, 360). Center sector 0 on north
    # by rotating half a sector before bucketing.
    bearing = math.degrees(math.atan2(dx, dy)) % 360.0
    sector_size = 360.0 / sectors
    sector_idx = int(((bearing + sector_size / 2.0) % 360.0) // sector_size)

    labels = _COMPASS.get(sectors)
    label = labels[sector_idx] if labels else f"S{sector_idx + 1}"
    return RingSector(ring=ring, sector_idx=sector_idx, sector_label=label)
