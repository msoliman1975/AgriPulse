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

THE BLOCKS DO NOT SHARE A GRID
-----------------------------
Measured on prod, three blocks of the SAME pass:

    9.903 x 10.076 m   origin 464709.07, 3327497.56
   10.036 x 10.056 m   origin 464703.99, 3328003.39
   10.134 x  9.938 m   origin 465204.22, 3327500.58

The provider returns a fixed-SIZE image fitted to each requested AOI, not a
fixed-RESOLUTION window on a shared lattice, so every block carries its own
pixel size and an arbitrary origin. Merging them without saying otherwise
resamples everything onto whichever block happens to be read first — an
arbitrary choice that would move values by up to half a pixel and vary between
runs if the block order changed.

So the merge targets an EXPLICIT grid: the product's native resolution, with
the extent snapped to a whole multiple of it (`target_aligned_pixels`). That
makes a farm raster deterministic, comparable between scenes, and independent
of which block was read first.

The consequence is worth stating plainly: block statistics measured on this
grid cannot be bit-identical to the stored ones, which were computed on each
block's own arbitrary grid. `verify_farm_raster_aggregates` exists to say how
far apart they land, and the answer decides whether the cutover is safe.
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
    resolution_m: float | None = None,
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

            # Target an explicit grid rather than inheriting the first
            # dataset's. See the module docstring: the blocks arrive on
            # different pixel sizes and unaligned origins, so "whichever was
            # read first" is not a grid anyone chose. Snapping the extent to a
            # whole multiple of the resolution makes the result the same
            # whatever order the blocks are read in.
            res = resolution_m or _median_resolution(datasets)
            mosaic, transform = rio_merge(
                datasets,
                nodata=float("nan"),
                res=(res, res),
                target_aligned_pixels=True,
            )
            base_profile = datasets[0].profile.copy()
    finally:
        for ds in datasets:
            ds.close()

    bands_arrays = {
        name: mosaic[i].astype(np.float32, copy=False) for i, name in enumerate(band_names)
    }
    if count == n_science + 1:
        # Only where there is actually a scene classification to read. A farm
        # mosaic has NaN in the gaps between blocks, and `scl_cloud_mask` casts
        # to int16 — NaN casts to garbage, some of which lands on a cloud code,
        # so an unguarded mask reports cloud over ground that has no pixels at
        # all. Harmless downstream (those pixels are nodata anyway) but it
        # inflates every "how cloudy was this pass" number computed from it.
        scl = mosaic[n_science].astype(np.float32, copy=False)
        cloud_mask = np.where(np.isfinite(scl), scl_cloud_mask(np.nan_to_num(scl)), False)
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


def _median_resolution(datasets: list[Any]) -> float:
    """Fallback grid size when the product's native resolution is unknown.

    The median of what the blocks actually carry, rather than the first one's:
    a single oddly-shaped AOI should not set the grid for the whole farm.
    """
    sizes = sorted(abs(ds.transform.a) for ds in datasets)
    return float(sizes[len(sizes) // 2])


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
