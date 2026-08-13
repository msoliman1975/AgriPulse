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


def _write_at(
    path, *, origin_x: float, origin_y: float, res: float, size: int, value: float
) -> str:
    """A tile on its OWN grid — the provider fits a fixed-size image to each
    requested AOI, so real blocks arrive with different pixel sizes and
    origins that line up with nothing."""
    transform = from_origin(origin_x, origin_y, res, res)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=len(BANDS),
        dtype="float32",
        crs="EPSG:32636",
        transform=transform,
        nodata=float("nan"),
    ) as ds:
        for i in range(len(BANDS)):
            ds.write(np.full((size, size), value, dtype="float32"), i + 1)
    return str(path)


def test_grid_does_not_depend_on_which_block_is_read_first(tmp_path):
    # Two blocks on genuinely different grids, as prod actually stores them:
    # 9.9m vs 10.13m pixels, origins aligned to nothing.
    a = _write_at(
        tmp_path / "a.tif", origin_x=464709.07, origin_y=3327497.56, res=9.903, size=20, value=0.2
    )
    b = _write_at(
        tmp_path / "b.tif", origin_x=464703.99, origin_y=3328003.39, res=10.134, size=20, value=0.6
    )

    one, _c1, p1 = merge_block_rasters([a, b], band_names=BANDS, resolution_m=10.0)
    two, _c2, p2 = merge_block_rasters([b, a], band_names=BANDS, resolution_m=10.0)

    # Same grid whichever order they arrive in. Without an explicit target the
    # mosaic inherits the first dataset's pixel size and origin, so this would
    # differ run to run.
    assert (p1["width"], p1["height"]) == (p2["width"], p2["height"])
    assert p1["transform"] == p2["transform"]
    assert one["red"].shape == two["red"].shape


def test_grid_is_snapped_to_whole_multiples_of_the_resolution(tmp_path):
    # An origin on no particular lattice must still produce a grid that is,
    # so two scenes of the same farm land on the same pixels and can be
    # compared date to date.
    a = _write_at(
        tmp_path / "a.tif", origin_x=464709.07, origin_y=3327497.56, res=9.903, size=10, value=0.4
    )
    _bands, _cloud, profile = merge_block_rasters([a], band_names=BANDS, resolution_m=10.0)
    t = profile["transform"]
    assert t.a == 10.0
    assert -t.e == 10.0
    assert t.c % 10.0 == 0
    assert t.f % 10.0 == 0


def test_cloud_mask_ignores_the_gaps_between_blocks(tmp_path):
    # A farm mosaic has NaN where no block was fetched. `scl_cloud_mask` casts
    # to int16, and NaN casts to garbage that can land on a cloud code — so an
    # unguarded mask claims cloud over ground with no pixels at all.
    transform = from_origin(ORIGIN_X, ORIGIN_Y, PIXEL, PIXEL)
    path = tmp_path / "gap.tif"
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
            band = np.full((2, 2), 0.3, dtype="float32")
            band[1, 1] = np.nan  # one corner never fetched
            ds.write(band, i + 1)
        scl = np.array([[4, 4], [4, np.nan]], dtype="float32")
        ds.write(scl, len(BANDS) + 1)

    _bands, cloud, _profile = merge_block_rasters([str(path)], band_names=BANDS)

    # Nothing is cloudy: three clear pixels and one with no data at all.
    assert not cloud.any()
