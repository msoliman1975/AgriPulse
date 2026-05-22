"""Unit tests for the per-cell zonal-stats helper.

We hand the function a tiny synthetic raster + an Affine transform we
construct by hand, then assert it picks the correct pixels for a few
cell polygons. No rasterio file I/O — keeps the test fast and the
geometry math easy to follow.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
from rasterio.transform import Affine

from app.modules.grid.zonal import CellAggregates, compute_cell_aggregates

# A 4x4 raster on a 10m pixel grid anchored at (1000, 2000). Pixel (0,0)
# is in the NW corner — rasterio's Affine convention puts +y *down*, so
# the transform's e (y-pixel scale) is negative.
#
# Pixel x extent: 1000..1040 (cols 0..3)
# Pixel y extent: 2000..1960 (rows 0..3 going south)
#
# Values: increase left→right across each row, so a 2x2 cell starting at
# col 1 should mean (1.0 + 2.0 + 5.0 + 6.0) / 4 = 3.5
RASTER = np.array(
    [
        [0.0, 1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0, 7.0],
        [8.0, 9.0, 10.0, 11.0],
        [12.0, 13.0, 14.0, 15.0],
    ],
    dtype=np.float32,
)
# rasterio.transform.from_origin(west, north, xsize, ysize)
TRANSFORM = Affine.translation(1000.0, 2000.0) * Affine.scale(10.0, -10.0)


def _cell_wkt(x_min: float, y_min: float, x_max: float, y_max: float) -> str:
    return (
        f"POLYGON (({x_min} {y_min}, {x_max} {y_min}, "
        f"{x_max} {y_max}, {x_min} {y_max}, {x_min} {y_min}))"
    )


def test_compute_cell_aggregates_single_pixel_cell() -> None:
    # Cell exactly over pixel (0,0) — value 0.0.
    cell = _cell_wkt(1000, 1990, 1010, 2000)
    agg = compute_cell_aggregates(
        raster=RASTER, transform=TRANSFORM, cell_polygon_wkt=cell
    )
    assert agg.valid_pixel_count == 1
    assert agg.total_pixel_count == 1
    assert agg.mean == Decimal("0.0000")
    assert agg.std_dev is None  # too few samples for std


def test_compute_cell_aggregates_2x2_cell() -> None:
    # Cell covering pixels (row 0..1, col 1..2): values 1, 2, 5, 6.
    # mean = 3.5, min = 1, max = 6, std = 1.802776 → 1.8028.
    cell = _cell_wkt(1010, 1980, 1030, 2000)
    agg = compute_cell_aggregates(
        raster=RASTER, transform=TRANSFORM, cell_polygon_wkt=cell
    )
    assert agg.valid_pixel_count == 4
    assert agg.total_pixel_count == 4
    assert agg.mean == Decimal("3.5000")
    assert agg.min == Decimal("1.0000")
    assert agg.max == Decimal("6.0000")
    assert agg.std_dev is not None
    # numpy.std default is population std: sqrt(((1-3.5)^2 + (2-3.5)^2 + ...) / 4)
    expected = float(np.std([1.0, 2.0, 5.0, 6.0]))
    assert abs(float(agg.std_dev) - expected) < 0.001


def test_compute_cell_aggregates_ignores_nan_pixels() -> None:
    raster = RASTER.copy()
    raster[0, 1] = np.nan  # one of the four pixels is masked
    cell = _cell_wkt(1010, 1980, 1030, 2000)
    agg = compute_cell_aggregates(
        raster=raster, transform=TRANSFORM, cell_polygon_wkt=cell
    )
    # Remaining pixels: 2, 5, 6 — mean = 13/3 = 4.3333
    assert agg.valid_pixel_count == 3
    assert agg.total_pixel_count == 4
    assert agg.mean == Decimal("4.3333")


def test_compute_cell_aggregates_all_nan_returns_nulls() -> None:
    raster = np.full_like(RASTER, np.nan)
    cell = _cell_wkt(1010, 1980, 1030, 2000)
    agg = compute_cell_aggregates(
        raster=raster, transform=TRANSFORM, cell_polygon_wkt=cell
    )
    assert agg.valid_pixel_count == 0
    assert agg.total_pixel_count == 4
    assert agg.mean is None
    assert agg.min is None
    assert agg.max is None
    assert agg.std_dev is None


def test_compute_cell_aggregates_cell_off_raster() -> None:
    # Cell completely outside the raster bounds — zero pixels.
    cell = _cell_wkt(5000, 5000, 5010, 5010)
    agg = compute_cell_aggregates(
        raster=RASTER, transform=TRANSFORM, cell_polygon_wkt=cell
    )
    assert agg == CellAggregates(None, None, None, None, 0, 0)
