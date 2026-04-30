"""Unit tests for the grid-based auto-blocking algorithm."""

from __future__ import annotations

import pytest

from app.modules.farms.auto_grid import auto_grid_candidates
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
