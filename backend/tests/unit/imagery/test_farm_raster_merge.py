"""Merging per-block rasters into one farm surface.

These are the properties the whole farm-raster change rests on:

  * a pixel shared by two adjacent blocks appears ONCE, which is what removes
    the dark seam on the map;
  * ground that no block covered stays nodata, so a farm-wide raster never
    invents a value over land nobody photographed;
  * a block whose object is missing is skipped rather than sinking the farm —
    on prod, 3,787 AOI-scenes have a job row claiming success with nothing
    behind it.

Synthetic GeoTIFFs on a shared grid, so this runs with no network and no
bucket.
"""

from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.modules.imagery.farm_raster import (
    NoBlockRastersError,
    covered_mask,
    merge_block_rasters,
)

BANDS = ("blue", "green", "red", "nir")
# 10 m pixels on a UTM-like grid, so "one pixel east" is +10 in x.
PIXEL = 10.0
ORIGIN_X = 500_000.0
ORIGIN_Y = 3_300_000.0


def _write(path, *, col_offset: int, width: int, height: int, value: float) -> str:
    """A 4-band tile whose top-left sits `col_offset` pixels east of origin."""
    transform = from_origin(ORIGIN_X + col_offset * PIXEL, ORIGIN_Y, PIXEL, PIXEL)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": len(BANDS),
        "dtype": "float32",
        "crs": "EPSG:32636",
        "transform": transform,
        "nodata": float("nan"),
    }
    with rasterio.open(path, "w", **profile) as ds:
        for i in range(len(BANDS)):
            ds.write(np.full((height, width), value, dtype="float32"), i + 1)
    return str(path)


def test_shared_boundary_pixel_lands_once(tmp_path):
    # Two 4x4 blocks that overlap by one column — exactly what `all_touched`
    # clipping produces for neighbours sharing an edge.
    a = _write(tmp_path / "a.tif", col_offset=0, width=4, height=4, value=0.2)
    b = _write(tmp_path / "b.tif", col_offset=3, width=4, height=4, value=0.2)

    bands, _cloud, profile = merge_block_rasters([a, b], band_names=BANDS)

    # 4 + 4 columns minus the one they share.
    assert profile["width"] == 7
    assert profile["height"] == 4
    assert bands["red"].shape == (4, 7)
    # Every pixel carries the value once — no doubling where they met.
    assert np.allclose(bands["red"], 0.2)


def test_ground_no_block_covered_stays_nodata(tmp_path):
    # Two blocks with a two-pixel gap between them: the farm has land there,
    # nobody ever fetched it.
    a = _write(tmp_path / "a.tif", col_offset=0, width=3, height=3, value=0.5)
    b = _write(tmp_path / "b.tif", col_offset=5, width=3, height=3, value=0.5)

    bands, _cloud, profile = merge_block_rasters([a, b], band_names=BANDS)

    assert profile["width"] == 8
    covered = covered_mask(bands)
    # Columns 3 and 4 are the untouched gap.
    assert covered[:, :3].all()
    assert not covered[:, 3:5].any()
    assert covered[:, 5:].all()
    # And the gap is NaN rather than zero — zero is a legitimate reflectance.
    assert np.isnan(bands["red"][:, 3:5]).all()


def test_a_missing_object_does_not_sink_the_farm(tmp_path):
    good = _write(tmp_path / "good.tif", col_offset=0, width=3, height=3, value=0.4)
    missing = str(tmp_path / "not-written.tif")

    bands, _cloud, profile = merge_block_rasters([good, missing], band_names=BANDS)

    assert profile["width"] == 3
    assert np.allclose(bands["red"], 0.4)


def test_no_readable_raster_is_an_error_not_an_empty_surface(tmp_path):
    # Better to fail loudly than to write a farm raster of pure nodata and
    # have the console report a farm with no vegetation.
    with pytest.raises(NoBlockRastersError):
        merge_block_rasters([str(tmp_path / "nope.tif")], band_names=BANDS)

    with pytest.raises(NoBlockRastersError):
        merge_block_rasters([], band_names=BANDS)


def test_scl_band_becomes_a_cloud_mask(tmp_path):
    # A raw COG may carry a trailing scene-classification band. Value 9 is
    # "high probability cloud" in the Sentinel-2 SCL vocabulary.
    transform = from_origin(ORIGIN_X, ORIGIN_Y, PIXEL, PIXEL)
    path = tmp_path / "scl.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=len(BANDS) + 1,
        dtype="float32",
        crs="EPSG:32636",
        transform=transform,
        nodata=float("nan"),
    ) as ds:
        for i in range(len(BANDS)):
            ds.write(np.full((2, 2), 0.3, dtype="float32"), i + 1)
        ds.write(np.array([[9, 4], [4, 9]], dtype="float32"), len(BANDS) + 1)

    bands, cloud, _profile = merge_block_rasters([str(path)], band_names=BANDS)

    assert set(bands) == set(BANDS)
    assert cloud.tolist() == [[True, False], [False, True]]
