"""Unit tests for the pivot ring/sector labeler."""

from __future__ import annotations

import math

from app.modules.grid.polar_label import ring_sector

CENTER_LAT = 30.0
CENTER_LON = 32.0


def _at(bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """(lon, lat) of a point `dist_m` from center at `bearing_deg` (CW from N)."""
    dx = dist_m * math.sin(math.radians(bearing_deg))  # east
    dy = dist_m * math.cos(math.radians(bearing_deg))  # north
    lat = CENTER_LAT + dy / 110_540.0
    lon = CENTER_LON + dx / (111_320.0 * math.cos(math.radians(CENTER_LAT)))
    return lon, lat


def _rs(bearing_deg: float, dist_m: float, *, ring_width: float, sectors: int):
    lon, lat = _at(bearing_deg, dist_m)
    return ring_sector(
        centroid_lon=lon,
        centroid_lat=lat,
        center_lon=CENTER_LON,
        center_lat=CENTER_LAT,
        ring_width_m=ring_width,
        sector_count=sectors,
    )


def test_center_is_ring_one() -> None:
    rs = _rs(0, 0.0, ring_width=20, sectors=4)
    assert rs.ring == 1


def test_ring_index_scales_with_distance() -> None:
    # 50m / 20m ring width -> floor(2.5) + 1 = ring 3.
    rs = _rs(0, 50.0, ring_width=20, sectors=4)
    assert rs.ring == 3


def test_quadrant_sector_labels() -> None:
    assert _rs(0, 30, ring_width=20, sectors=4).sector_label == "N"
    assert _rs(90, 30, ring_width=20, sectors=4).sector_label == "E"
    assert _rs(180, 30, ring_width=20, sectors=4).sector_label == "S"
    assert _rs(270, 30, ring_width=20, sectors=4).sector_label == "W"


def test_octant_sector_label() -> None:
    rs = _rs(45, 100, ring_width=25, sectors=8)
    assert rs.ring == 5
    assert rs.sector_label == "NE"


def test_unknown_sector_count_falls_back_to_numbered() -> None:
    rs = _rs(0, 30, ring_width=20, sectors=6)
    assert rs.sector_label == "S1"
