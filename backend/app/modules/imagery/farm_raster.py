"""One raster per farm, stitched from the per-block bands we already store.

WHY THIS EXISTS
---------------
Imagery is fetched, stored and computed per BLOCK AOI. A 36-block farm turns
one satellite pass into 36 rasters of ~50x50 pixels, and that shape leaks into
the product in three ways:

  * land inside the farm boundary but outside every block has NO PIXELS AT
    ALL — a quarter of the reference farm (50.3 of 203.4 feddan) is not
    "uncoloured", it is unmeasured;
  * adjacent blocks share a boundary pixel, because each block's raster is cut
    with ``all_touched``. Drawing both puts two translucent copies of the same
    ground on top of each other, which reads as a dark seam;
  * the map needs one tile source per block, so a farm view cannot ask for
    fewer than one tile per block however the client is tuned.

A single farm raster is about six times fewer pixels than the 36 block rasters
it replaces, in one file rather than 36.

WHY IT STITCHES RATHER THAN RE-FETCHES
--------------------------------------
The raw 8-band rasters for every past scene are already in the bucket. Merging
them costs worker time and no provider quota, and it is the only path that can
rebuild years of history without re-buying it. The merged surface covers the
union of the blocks, not the whole farm boundary: ground that was never fetched
stays nodata, and honestly so. New scenes fetched at the farm AOI will fill it.

The merge is a plain "last one wins" over a common grid. Every block raster for
one scene comes from the same Sentinel tile, so overlapping edge pixels hold
the same value and the choice does not matter — but it does mean a shared
boundary pixel is written ONCE, which is what removes the seam.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from rasterio.merge import merge as rio_merge
from shapely.geometry import shape

from app.modules.imagery._rasterio_io import _gdal_s3_env
from app.modules.indices.computation import scl_cloud_mask


class NoBlockRastersError(RuntimeError):
    """No block raster could be read for this farm and scene."""


def merge_block_rasters(
    raw_uris: list[str],
    *,
    band_names: tuple[str, ...],
) -> tuple[dict[str, NDArray[np.float32]], NDArray[np.bool_], dict[str, Any]]:
    """Merge per-block raw rasters into one farm-wide band stack.

    Returns ``(bands_arrays, cloud_mask, write_profile)`` in the same shapes
    ``load_raw_bands_and_aggregate`` returns, so the existing
    ``compute_and_write_indices`` can consume this without knowing whether it
    is looking at one block or a whole farm.

    There is deliberately NO aoi_mask in the return. A block raster is masked
    to its own boundary at fetch time; the farm surface is the union of what
    was fetched, and the caller masks per block or per cell when it needs an
    aggregate. Masking the merge to the farm boundary here would throw away
    the ``all_touched`` fringe that block aggregates currently count, and the
    whole point of the pilot is that block means do not move.
    """
    if not raw_uris:
        raise NoBlockRastersError("no raw rasters to merge")

    n_science = len(band_names)
    datasets = []
    try:
        with _gdal_s3_env():
            for uri in raw_uris:
                try:
                    datasets.append(rasterio.open(uri))
                except rasterio.errors.RasterioIOError:
                    # A block whose object is missing must not sink the farm:
                    # ~3,787 AOI-scenes on prod have a job row claiming success
                    # with nothing behind it. Skip it; the farm raster is then
                    # short one block, which is visible rather than wrong.
                    continue
            if not datasets:
                raise NoBlockRastersError("every raw raster failed to open")

            counts = {ds.count for ds in datasets}
            if len(counts) != 1:
                raise ValueError(f"block rasters disagree on band count: {sorted(counts)}")
            count = counts.pop()
            if count not in (n_science, n_science + 1):
                raise ValueError(
                    f"raw COGs carry {count} bands; expected {n_science} or "
                    f"{n_science + 1} (science bands {band_names!r} + optional SCL)"
                )

            # `merge` reprojects nothing — every block of one scene shares the
            # source CRS and pixel grid, so the mosaic lands on that same grid
            # and a pixel keeps its exact value and position.
            mosaic, transform = rio_merge(datasets, nodata=float("nan"))
            base_profile = datasets[0].profile.copy()
    finally:
        for ds in datasets:
            ds.close()

    bands_arrays = {
        name: mosaic[i].astype(np.float32, copy=False) for i, name in enumerate(band_names)
    }
    if count == n_science + 1:
        cloud_mask = scl_cloud_mask(mosaic[n_science].astype(np.float32, copy=False))
    else:
        cloud_mask = np.zeros(mosaic.shape[1:], dtype=bool)

    write_profile: dict[str, Any] = {
        **base_profile,
        "count": 1,
        "dtype": "float32",
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "predictor": 2,
        "nodata": float("nan"),
        "height": mosaic.shape[1],
        "width": mosaic.shape[2],
        "transform": transform,
    }
    return bands_arrays, cloud_mask, write_profile


def covered_mask(bands_arrays: dict[str, NDArray[np.float32]]) -> NDArray[np.bool_]:
    """Where the merged surface actually has data.

    Stands in for the per-block AOI mask: a pixel counts when the first band
    is finite. Gaps between blocks are nodata and stay out of every aggregate,
    which is what keeps a farm-wide raster from inventing values over ground
    nobody fetched.
    """
    first = next(iter(bands_arrays.values()))
    return np.isfinite(first)


def block_masks_on_grid(
    profile: dict[str, Any],
    boundaries_utm: dict[str, dict[str, Any]],
) -> dict[str, NDArray[np.bool_]]:
    """Boolean masks for each block, on the FARM raster's grid.

    A block aggregate over the farm surface is that surface masked to the
    block's own polygon — the same polygon, and the same ``all_touched``
    rule, the per-block pipeline uses when it cuts a block its own raster.
    Keeping both identical is what makes a difference in the resulting means
    a real finding rather than an artefact of how the pixels were selected.

    The merge preserves the source pixel grid, so rasterising a block against
    the farm transform selects exactly the pixels its own raster held.
    """
    out: dict[str, NDArray[np.bool_]] = {}
    shape_hw = (int(profile["height"]), int(profile["width"]))
    for block_id, geojson in boundaries_utm.items():
        out[block_id] = ~geometry_mask(
            [shape(geojson)],
            out_shape=shape_hw,
            transform=profile["transform"],
            invert=False,
            all_touched=True,
        )
    return out
