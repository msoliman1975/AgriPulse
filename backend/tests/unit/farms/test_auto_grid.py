"""Unit tests for the grid-based auto-blocking algorithm."""

from __future__ import annotations

import math

import pytest

from app.modules.farms.auto_grid import auto_grid_candidates, cell_size_for_max_area_m2
from app.modules.farms.errors import GeometryInvalidError


def _square(lon: float, lat: float, side: float) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + side, lat],
                [lon + side, lat + side],
                [lon, lat + side],
                [lon, lat],
            ]
        ],
    }


def test_500m_grid_over_small_farm() -> None:
    # ~1km x 1km square near Cairo.
    farm = _square(31.2, 30.0, 0.01)  # 0.01° ≈ 1.1km in latitude
    cells = auto_grid_candidates(farm, cell_size_m=500)
    # Expect a 2x3 or 3x3 grid depending on rounding — at least 4 candidates.
    assert len(cells) >= 4
    # Each candidate is a closed Polygon with 5 coordinates (4 + closing).
    for cell in cells:
        coords = cell["geometry"]["coordinates"][0]  # type: ignore[index]
        assert len(coords) == 5
        assert coords[0] == coords[-1]
        assert cell["code"].startswith("AG-R")


def test_cell_size_must_be_positive_and_in_range() -> None:
    farm = _square(31.2, 30.0, 0.01)
    with pytest.raises(GeometryInvalidError):
        auto_grid_candidates(farm, cell_size_m=5)
    with pytest.raises(GeometryInvalidError):
        auto_grid_candidates(farm, cell_size_m=10000)


def test_cell_size_for_max_area_inverts_to_side_length() -> None:
    # A 5-feddan cap (≈ 21_004 m²) maps to a ~145 m square cell.
    assert cell_size_for_max_area_m2(5 * 4200.83) == 145
    # A perfect square: 40_000 m² → 200 m edge.
    assert cell_size_for_max_area_m2(40_000) == 200


def test_cell_size_for_max_area_clamps_to_supported_range() -> None:
    # Tiny target clamps up to the 10 m floor, huge target down to the 5000 m ceiling.
    assert cell_size_for_max_area_m2(1.0) == 10
    assert cell_size_for_max_area_m2(10_000_000_000) == 5000


def test_cell_size_for_max_area_rejects_nonpositive() -> None:
    with pytest.raises(GeometryInvalidError):
        cell_size_for_max_area_m2(0)


def test_unsupported_geometry_type() -> None:
    with pytest.raises(GeometryInvalidError):
        auto_grid_candidates({"type": "Point", "coordinates": [31.0, 30.0]}, cell_size_m=100)


def test_multipolygon_input() -> None:
    geom = {
        "type": "MultiPolygon",
        "coordinates": [_square(31.2, 30.0, 0.01)["coordinates"]],
    }
    cells = auto_grid_candidates(geom, cell_size_m=500)
    assert len(cells) >= 4


def _point_in_ring(px: float, py: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def test_candidates_never_spill_past_a_triangular_aoi() -> None:
    # A right triangle AoI: the hypotenuse cuts diagonally across cells, so
    # honouring the boundary forces non-rectangular clipped candidates and
    # forbids any vertex from landing outside the triangle.
    tri = {
        "type": "Polygon",
        "coordinates": [[[31.20, 30.00], [31.22, 30.00], [31.20, 30.02], [31.20, 30.00]]],
    }
    ring = tri["coordinates"][0]
    cells = auto_grid_candidates(tri, cell_size_m=300)
    assert cells

    # Every emitted vertex must sit inside (or essentially on) the AoI.
    tol = 1e-6
    for cell in cells:
        for x, y in cell["geometry"]["coordinates"][0]:  # type: ignore[index]
            on_edge_or_in = _point_in_ring(x, y, ring) or _near_edge(x, y, ring, tol)
            assert on_edge_or_in, f"vertex ({x}, {y}) spills outside the AoI"

    # At least one candidate is clipped to a non-rectangle (the hypotenuse).
    assert any(len(c["geometry"]["coordinates"][0]) != 5 for c in cells)  # type: ignore[index]


def _near_edge(px: float, py: float, ring: list[tuple[float, float]], tol: float) -> bool:
    n = len(ring)
    for i in range(n - 1):
        ax, ay = ring[i]
        bx, by = ring[i + 1]
        # Distance from point to segment AB.
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            continue
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
        cx, cy = ax + t * dx, ay + t * dy
        if math.hypot(px - cx, py - cy) <= tol:
            return True
    return False


def test_edge_cell_area_is_clipped_not_full() -> None:
    # A cell straddling the boundary should report less than a full cell's area.
    tri = {
        "type": "Polygon",
        "coordinates": [[[31.20, 30.00], [31.22, 30.00], [31.20, 30.02], [31.20, 30.00]]],
    }
    cells = auto_grid_candidates(tri, cell_size_m=300)
    full = 300 * 300
    assert any(float(c["area_m2"]) < full * 0.99 for c in cells)
    # No candidate exceeds a full cell (clipping can only shrink).
    assert all(float(c["area_m2"]) <= full + 1.0 for c in cells)


def test_interior_cells_stay_whole_rectangles() -> None:
    # A square farm large relative to the cell: interior cells are untouched
    # full rectangles (5 coords) with full-cell area.
    farm = _square(31.2, 30.0, 0.02)
    cells = auto_grid_candidates(farm, cell_size_m=400)
    full = 400 * 400
    assert any(
        len(c["geometry"]["coordinates"][0]) == 5 and abs(float(c["area_m2"]) - full) < 1.0  # type: ignore[index]
        for c in cells
    )
