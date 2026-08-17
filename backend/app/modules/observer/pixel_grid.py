"""Pixel and cell footprints for one scene, as map-ready geometry.

The pixel inspector answers "what is this one pixel?". This answers the
question underneath it — *how does a pixel become a cell, and a cell a block?*
— by handing the map every pixel footprint with its value, every grid cell
with its stored aggregate, and the block aggregate they roll up into.

**Cells and blocks claim pixels differently, and that is not a bug.** The
pipeline rasterises the block AOI with ``all_touched=True`` (a pixel counts if
its footprint touches the boundary) and cells with ``all_touched=False`` (a
pixel counts only if its *centre* falls inside). So the per-cell counts do not
sum to the block count, and an operator comparing them would otherwise
conclude something is broken. Both rules are reproduced here exactly —
`geometry_mask` with the same flags the pipeline uses — and the discrepancy is
reported rather than hidden.

Bounded on purpose: a block's AOI is usually a few hundred 10 m pixels, but
nothing stops one being enormous. Past ``max_pixels`` the response is
truncated and says so, rather than shipping a 65k-feature GeoJSON that would
lock up the browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform as warp_transform
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping, shape

from app.core.logging import get_logger
from app.modules.imagery._rasterio_io import _gdal_s3_env
from app.modules.indices.computation import compute_indices_for_product, quality_band_mask

_log = get_logger(__name__)

# Above this the browser is the bottleneck, not the read. 4,000 pixel polygons
# is ~1.5 MB of GeoJSON and still interactive; a 256x256 raster fully inside an
# AOI would be 65,536.
DEFAULT_MAX_PIXELS = 4000


@dataclass(frozen=True, slots=True)
class PixelFeature:
    row: int
    col: int
    value: float | None
    masked: bool
    # WGS84 polygon of the pixel's ground footprint.
    geometry: dict[str, Any]
    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class PixelGrid:
    index_code: str
    resolution_m: float
    pixels: list[PixelFeature]
    aoi_pixel_count: int
    returned_pixel_count: int
    truncated: bool
    # Recomputed from exactly the pixels returned, so the UI can show the
    # arithmetic rather than asserting it.
    recomputed_mean: float | None
    recomputed_valid: int


# Degrees, ~1 cm at the equator. The pixels are 10-30 m across, so more
# precision than this only inflates the payload — 4,000 polygons carry
# 40,000 coordinate pairs.
_COORD_DP = 7


def _pixel_polygons_wgs84(
    rows: Any, cols: Any, transform: Any, src_crs: Any
) -> tuple[list[dict[str, Any]], list[float], list[float]]:
    """Every pixel's ground footprint, reprojected for the map — in ONE pass.

    Built from the affine transform rather than by sampling, so each polygon
    is the pixel's true extent — the thing that decides AOI membership under
    `all_touched`, not an approximation of it.

    Vectorised deliberately. The previous shape called `transform_geom` once
    per pixel, which builds a fresh PROJ transformer every time: measured on
    prod at ~12 ms per pixel, so the default 4,000-pixel grid took **50
    seconds** and the map read as broken. One `warp_transform` over all the
    corners at once is the same arithmetic with one setup.
    """
    c = np.asarray(cols, dtype=np.float64)
    r = np.asarray(rows, dtype=np.float64)
    # Affine applied directly: x = c + a*col + b*row, y = f + d*col + e*row.
    # North-up rasters have b = d = 0, but carrying them keeps this correct
    # for a rotated transform rather than quietly wrong.
    x0 = transform.c + transform.a * c + transform.b * r
    y0 = transform.f + transform.d * c + transform.e * r
    x1 = transform.c + transform.a * (c + 1) + transform.b * (r + 1)
    y1 = transform.f + transform.d * (c + 1) + transform.e * (r + 1)

    xmin, xmax = np.minimum(x0, x1), np.maximum(x0, x1)
    ymin, ymax = np.minimum(y0, y1), np.maximum(y0, y1)

    # Four corners plus the centre, all transformed in a single call.
    xs = np.concatenate([xmin, xmax, xmax, xmin, (xmin + xmax) / 2.0])
    ys = np.concatenate([ymin, ymin, ymax, ymax, (ymin + ymax) / 2.0])
    lon, lat = warp_transform(src_crs, "EPSG:4326", xs.tolist(), ys.tolist())

    n = len(c)
    lon_a = np.round(np.asarray(lon, dtype=np.float64), _COORD_DP)
    lat_a = np.round(np.asarray(lat, dtype=np.float64), _COORD_DP)

    geoms: list[dict[str, Any]] = []
    for i in range(n):
        ring = [
            [float(lon_a[i]), float(lat_a[i])],
            [float(lon_a[n + i]), float(lat_a[n + i])],
            [float(lon_a[2 * n + i]), float(lat_a[2 * n + i])],
            [float(lon_a[3 * n + i]), float(lat_a[3 * n + i])],
        ]
        # GeoJSON rings close explicitly.
        ring.append(list(ring[0]))
        geoms.append({"type": "Polygon", "coordinates": [ring]})

    centres_lon = [float(v) for v in lon_a[4 * n :]]
    centres_lat = [float(v) for v in lat_a[4 * n :]]
    return geoms, centres_lon, centres_lat


def build_pixel_grid(
    *,
    product_code: str,
    air_temp_c: float | None = None,
    raw_uri: str,
    band_names: tuple[str, ...],
    aoi_geojson_utm: dict[str, Any],
    index_code: str,
    cell_polygon_wkt: str | None = None,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> PixelGrid:
    """Every pixel the AOI (or one cell) is made of, with its value.

    ``cell_polygon_wkt`` narrows to a single cell and switches the membership
    rule from the block's ``all_touched=True`` to the cell's
    ``all_touched=False`` — matching `grid.zonal.compute_cell_aggregates`
    exactly, so the pixels shown are the pixels the stored cell mean was
    actually computed from.

    ``product_code`` decides the mask ruleset and the index set, through the
    pipeline's own dispatchers. This module assumed Sentinel-2 twice over —
    `scl_cloud_mask` on whatever trailing band it found, and
    `compute_all_indices` on the band dict — so a Landsat thermal scene died
    on `KeyError: 'nir'`. That was unreachable while no thermal scene could
    be opened at all; making one openable is what surfaced it.

    ``air_temp_c`` is CWSI's second input, absent for every other product.
    """
    with _gdal_s3_env(), rasterio.open(raw_uri) as ds:
        n_science = len(band_names)
        arrays = {
            name: ds.read(idx + 1).astype(np.float32, copy=False)
            for idx, name in enumerate(band_names)
        }
        if ds.count == n_science + 1:
            cloud_mask = quality_band_mask(
                product_code, ds.read(n_science + 1).astype(np.float32, copy=False)
            )
        else:
            cloud_mask = np.zeros((ds.height, ds.width), dtype=bool)

        aoi_mask = ~geometry_mask(
            [shape(aoi_geojson_utm)],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=True,
        )
        if cell_polygon_wkt is not None:
            cell_poly = shapely_wkt.loads(cell_polygon_wkt)
            # `all_touched=False` — the cell rule. Using the block's rule here
            # would return pixels the stored cell mean never saw.
            in_cell = ~geometry_mask(
                [mapping(cell_poly)],
                out_shape=(ds.height, ds.width),
                transform=ds.transform,
                invert=False,
                all_touched=False,
            )
            selection = aoi_mask & in_cell
        else:
            selection = aoi_mask

        transform = ds.transform
        src_crs = ds.crs
        resolution = float(abs(transform.a))

    # Every index for the product gets computed, then nine tenths of it is
    # thrown away — s2_l2a has ten. Each one is a full-raster ufunc chain, so
    # the waste is real; but the maths must stay the pipeline's own, and
    # there is no per-index entry point. Discarding after the fact is the
    # honest trade: correct numbers first, and the dominant cost was never
    # here (it was the per-pixel CRS transform, see `_pixel_polygons_wgs84`).
    computed = compute_indices_for_product(product_code, arrays, air_temp_c=air_temp_c)
    if index_code not in computed:
        raise KeyError(index_code)
    raster = computed[index_code]
    clouded = np.where(cloud_mask, np.float32("nan"), raster)

    rows, cols = np.nonzero(selection)
    aoi_count = int(rows.size)
    truncated = aoi_count > max_pixels
    if truncated:
        _log.info(
            "observer_pixel_grid_truncated",
            aoi_pixels=aoi_count,
            max_pixels=max_pixels,
        )
        rows, cols = rows[:max_pixels], cols[:max_pixels]

    geoms, lons, lats = _pixel_polygons_wgs84(rows, cols, transform, src_crs)

    # Pull the per-pixel scalars out of the arrays in one vectorised gather
    # rather than indexing a numpy array 4,000 times in Python.
    raw_vals = clouded[rows, cols].astype(np.float64, copy=False)
    masked_flags = cloud_mask[rows, cols]
    finite_flags = np.isfinite(raw_vals)

    row_list = rows.tolist()
    col_list = cols.tolist()
    raw_list = raw_vals.tolist()
    masked_list = masked_flags.tolist()
    finite_list = finite_flags.tolist()

    pixels: list[PixelFeature] = [
        PixelFeature(
            row=row_list[i],
            col=col_list[i],
            value=raw_list[i] if finite_list[i] else None,
            masked=bool(masked_list[i]),
            geometry=geoms[i],
            lon=lons[i],
            lat=lats[i],
        )
        for i in range(len(row_list))
    ]
    values = [raw_list[i] for i in range(len(row_list)) if finite_list[i]]

    return PixelGrid(
        index_code=index_code,
        resolution_m=resolution,
        pixels=pixels,
        aoi_pixel_count=aoi_count,
        returned_pixel_count=len(pixels),
        truncated=truncated,
        # Deliberately computed from the returned pixels, not copied from the
        # stored row: showing the arithmetic is the point, and a mismatch
        # against the stored mean is a finding rather than a rendering bug.
        recomputed_mean=float(np.mean(values)) if values else None,
        recomputed_valid=len(values),
    )
