"""Masking a block against the farm grid selects the block's own pixels.

This is the claim the whole cutover rests on: measuring a block from a
farm-wide raster must give the same number as measuring it from its own
raster. If the masks disagree, every block series shifts at the changeover and
the difference would look like a data problem rather than a definition one.

The merge preserves the source pixel grid, so the two selections are the same
set of pixels — asserted here rather than assumed.
"""

from __future__ import annotations

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_origin

from app.modules.imagery.farm_raster import block_masks_on_grid, merge_block_rasters

BANDS = ("blue", "green", "red", "nir")
PIXEL = 10.0
ORIGIN_X = 500_000.0
ORIGIN_Y = 3_300_000.0


def _square(col_offset: int, cols: int, rows: int) -> dict:
    """A polygon covering an exact pixel window of the shared grid."""
    x0 = ORIGIN_X + col_offset * PIXEL
    x1 = x0 + cols * PIXEL
    y1 = ORIGIN_Y
    y0 = y1 - rows * PIXEL
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _write(path, *, col_offset: int, width: int, height: int, value: float) -> str:
    transform = from_origin(ORIGIN_X + col_offset * PIXEL, ORIGIN_Y, PIXEL, PIXEL)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=len(BANDS),
        dtype="float32",
        crs="EPSG:32636",
        transform=transform,
        nodata=float("nan"),
    ) as ds:
        for i in range(len(BANDS)):
            ds.write(np.full((height, width), value, dtype="float32"), i + 1)
    return str(path)


def test_block_mask_on_farm_grid_matches_the_blocks_own_mask(tmp_path):
    # Two adjacent 3x3 blocks, merged into one 6x3 farm surface.
    a = _write(tmp_path / "a.tif", col_offset=0, width=3, height=3, value=0.3)
    b = _write(tmp_path / "b.tif", col_offset=3, width=3, height=3, value=0.7)
    _bands, _cloud, farm_profile = merge_block_rasters([a, b], band_names=BANDS)

    geom_b = _square(col_offset=3, cols=3, rows=3)
    masks = block_masks_on_grid(farm_profile, {"b": geom_b})

    # The same polygon rasterised against block B's OWN raster — what the
    # per-block pipeline does today.
    with rasterio.open(b) as ds:
        own = ~geometry_mask(
            [geom_b],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=True,
        )

    farm_mask = masks["b"]
    assert farm_mask.shape == (3, 6)
    # Same pixel count, and positioned over B's half of the surface.
    assert farm_mask.sum() == own.sum()
    assert farm_mask[:, 3:].all()
    assert not farm_mask[:, :3].any()


def test_masked_farm_surface_reproduces_the_blocks_values(tmp_path):
    # Distinct values per block, so a mask that strays would change the mean.
    a = _write(tmp_path / "a.tif", col_offset=0, width=3, height=3, value=0.2)
    b = _write(tmp_path / "b.tif", col_offset=3, width=3, height=3, value=0.8)
    bands, _cloud, farm_profile = merge_block_rasters([a, b], band_names=BANDS)

    masks = block_masks_on_grid(
        farm_profile,
        {"a": _square(0, 3, 3), "b": _square(3, 3, 3)},
    )
    red = bands["red"]
    assert np.allclose(red[masks["a"]], 0.2)
    assert np.allclose(red[masks["b"]], 0.8)


def test_a_block_outside_the_fetched_ground_masks_to_nothing(tmp_path):
    # A block whose raster is missing from the merge selects no pixels rather
    # than borrowing a neighbour's — the farm surface must not invent it.
    a = _write(tmp_path / "a.tif", col_offset=0, width=3, height=3, value=0.4)
    _bands, _cloud, farm_profile = merge_block_rasters([a], band_names=BANDS)

    masks = block_masks_on_grid(farm_profile, {"far": _square(col_offset=20, cols=3, rows=3)})
    assert masks["far"].sum() == 0
