"""Cut a rendered image to a farm boundary.

The pipeline already cuts an index raster to the farm when it writes it,
but it can only cut on the raster's own pixel grid. The smallest step
there is one pixel: 10 m on Sentinel-2, 30 m on Landsat thermal. A pixel
whose centre falls inside the farm is stored whole, so the drawn surface
runs up to 5 m past a straight border and 7 m past a corner on
Sentinel-2, and three times that on the thermal product. Over the farm's
own outline that reads as a staircase of colour outside the field.

This algorithm cuts a second time, at render time, on the grid of the
image being returned. A tile is 512 pixels of screen, so the step it can
stop at is a screen pixel rather than a ground pixel, at every zoom.

Two things follow from doing it here rather than in the stored file:

* No raster is rewritten and no backfill is needed. The same stored file
  serves a cut tile and an uncut one.
* ``/cog/statistics`` takes the same parameter, so the legend and the map
  are cut by one rule. Measured on a real farm raster, the counts do not
  move: statistics are read at the raster's own resolution, where the
  stored mask already applied this rule. It matters when a raster is
  bigger than ``max_size`` and the read is decimated, and it keeps the
  two from drifting apart later.

The boundary lives beside the imagery at ``aoi/<aoi_hash>.geojson`` in
EPSG:4326. ``aoi_hash`` is a hash of the polygon, so the object is
content-addressed: it cannot describe a shape other than the one the
raster was cut from, and a cache entry stays valid for the life of the
process.

When the object is missing, the image is returned uncut. A farm whose
boundary was never published then draws exactly as it drew before this
existed, which is a visible fringe rather than an empty map.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from functools import lru_cache
from typing import Any

import numpy as np
import shapely
import shapely.geometry
from affine import Affine
from numpy.typing import NDArray
from rasterio.crs import CRS
from rasterio.warp import transform_geom
from rio_tiler.models import ImageData
from shapely.geometry.base import BaseGeometry
from titiler.core.algorithm import BaseAlgorithm

log = logging.getLogger(__name__)

WGS84 = CRS.from_epsg(4326)

# Tile side, in pixels, for the block decomposition in `_inside_mask`.
# 32 and 64 measured within a millisecond of each other on a 512 tile; 128
# was twice as slow, because a bigger block means more pixels tested one at
# a time along the boundary.
BLOCK = 32

# Prepared geometries are per thread. See `_projected`.
_local = threading.local()

# The parameter names an object under a fixed prefix, so it can only ever
# reach boundary files. Hashes are hex today; the class is wider so that
# changing the hash function does not need a change here.
AOI_RE = re.compile(r"^[A-Za-z0-9_-]{4,128}$")

# How long a missing boundary stays missing. Without this, the first tile
# drawn for a farm whose boundary is not published yet would pin "no
# cutline" for the life of the worker process.
MISSING_TTL_S = 300.0

_missing_since: dict[str, float] = {}


def _now() -> float:
    """Seam for the clock, so the miss memo can be tested."""
    return time.monotonic()


class Cutline(BaseAlgorithm):
    """Mask every pixel whose centre falls outside a stored AOI boundary."""

    aoi: str

    def __call__(self, img: ImageData) -> ImageData:
        """Return `img` with everything outside the boundary masked."""
        if boundary_geometry(self.aoi) is None:
            return img

        projected = _projected(self.aoi, img.crs)
        if projected is None:
            return img
        geom, (min_x, min_y, max_x, max_y) = projected

        img_min_x, img_min_y, img_max_x, img_max_y = img.bounds
        disjoint = (
            max_x <= img_min_x or min_x >= img_max_x or max_y <= img_min_y or min_y >= img_max_y
        )
        if disjoint:
            # No part of this image is inside the farm. Filling the mask
            # skips every geometry test that cannot change the answer.
            inside = np.zeros((img.height, img.width), dtype=bool)
        else:
            tile = shapely.box(img_min_x, img_min_y, img_max_x, img_max_y)
            if shapely.contains_properly(geom, tile):
                # Wholly inside the farm - the common case once a viewer
                # zooms in, and the cheapest possible answer.
                return img
            inside = _inside_mask(geom, img.transform, img.width, img.height)

        array = img.array.copy()
        array.mask = np.logical_or(np.ma.getmaskarray(array), ~inside)
        return ImageData(
            array,
            assets=img.assets,
            crs=img.crs,
            bounds=img.bounds,
            band_names=img.band_names,
            metadata=img.metadata,
            dataset_statistics=img.dataset_statistics,
        )


def boundary_geometry(aoi: str) -> dict[str, Any] | None:
    """The stored boundary for `aoi`, or None when there is not one.

    A missing object is remembered for `MISSING_TTL_S` so a farm without a
    published boundary does not cost one object read per tile, and starts
    being cut within five minutes of the boundary appearing.
    """
    if not AOI_RE.fullmatch(aoi):
        log.warning("cutline_bad_aoi aoi=%r", aoi[:64])
        return None

    since = _missing_since.get(aoi)
    if since is not None and _now() - since < MISSING_TTL_S:
        return None

    geometry = _load_cached(aoi)
    if geometry is None:
        _missing_since[aoi] = _now()
        return None
    _missing_since.pop(aoi, None)
    return geometry


def _inside_mask(
    geom: BaseGeometry,
    transform: Affine,
    width: int,
    height: int,
    block: int = BLOCK,
) -> NDArray[np.bool_]:
    """True where a pixel's centre falls inside `geom`.

    The straight way to do this is one point-in-polygon test per pixel, or
    `rasterio.features.geometry_mask`. Measured in the running image, both
    cost about 32 ms for one 512-pixel tile - a quarter of the ~123 ms the
    tile itself takes. Neither is affordable per tile.

    So the tile is cut into blocks first. A block wholly inside the farm is
    filled without testing a pixel, a block wholly outside is skipped, and
    only the blocks the boundary actually crosses pay for point-in-polygon
    work. Both block tests run as one vectorised call each. That takes the
    same tile to about 10 ms, and a tile the boundary misses to under one.

    Blocks are aligned to pixel 0, so a size that does not divide the tile
    still lines up; the trailing partial block is trimmed by the slice.
    """
    if transform.b or transform.d:
        # Rotated or sheared, so a column is not one x and a row is not one
        # y. No tiler hands back such an image, and rather than carry a
        # second coordinate path for it, fall back to the slow-but-general
        # rasterise.
        from rasterio.features import geometry_mask

        return geometry_mask(
            [geom], out_shape=(height, width), transform=transform, invert=True
        )

    nx = -(-width // block)
    ny = -(-height // block)
    px0 = np.arange(nx) * block
    px1 = np.minimum(px0 + block, width)
    py0 = np.arange(ny) * block
    py1 = np.minimum(py0 + block, height)

    # Pixel columns/rows to map coordinates. Tiles are north-up, so x grows
    # with the column and y falls with the row.
    x_left = transform.c + transform.a * px0
    x_right = transform.c + transform.a * px1
    y_top = transform.f + transform.e * py0
    y_bottom = transform.f + transform.e * py1

    x0, y0 = np.meshgrid(x_left, y_bottom)
    x1, y1 = np.meshgrid(x_right, y_top)
    boxes = shapely.box(x0, y0, x1, y1)

    hit = shapely.intersects(geom, boxes)
    full = shapely.contains_properly(geom, boxes)

    inside = np.repeat(np.repeat(full, block, axis=0), block, axis=1)[:height, :width]

    for iy, ix in np.argwhere(hit & ~full):
        cx0, cy0 = int(px0[ix]), int(py0[iy])
        cx1, cy1 = int(px1[ix]), int(py1[iy])
        xs = transform.c + transform.a * (np.arange(cx0, cx1) + 0.5)
        ys = transform.f + transform.e * (np.arange(cy0, cy1) + 0.5)
        inside[cy0:cy1, cx0:cx1] = shapely.contains_xy(geom, xs[None, :], ys[:, None])
    return inside


def _projected(
    aoi: str, crs: CRS
) -> tuple[BaseGeometry, tuple[float, float, float, float]] | None:
    """The boundary in the image's CRS, prepared for this thread.

    Shapely's prepared geometries build their index lazily on first use, so
    one shared object could be indexed by two request threads at once. The
    reprojection is cached and shared; the prepared copy is per thread.
    """
    crs_wkt = crs.to_wkt()
    try:
        wkb, bounds = _projected_cached(aoi, crs_wkt)
    except Exception:
        log.warning("cutline_reproject_failed aoi=%s", aoi, exc_info=True)
        return None

    mine: dict[tuple[str, str], BaseGeometry] | None = getattr(_local, "geoms", None)
    if mine is None:
        mine = _local.geoms = {}
    key = (aoi, crs_wkt)
    geom = mine.get(key)
    if geom is None:
        if len(mine) > 32:
            mine.clear()
        geom = shapely.from_wkb(wkb)
        shapely.prepare(geom)
        mine[key] = geom
    return geom, bounds


@lru_cache(maxsize=256)
def _projected_cached(aoi: str, crs_wkt: str) -> tuple[bytes, tuple[float, float, float, float]]:
    """Reproject once per (boundary, output CRS), not once per tile."""
    geometry = boundary_geometry(aoi)
    if geometry is None:  # pragma: no cover - the caller checks first
        raise ValueError(f"no boundary for {aoi}")
    geom = shapely.geometry.shape(transform_geom(WGS84, CRS.from_wkt(crs_wkt), geometry))
    return shapely.to_wkb(geom), tuple(geom.bounds)  # type: ignore[return-value]


@lru_cache(maxsize=512)
def _load_cached(aoi: str) -> dict[str, Any] | None:
    """Read one boundary object. Content-addressed, so cached for good."""
    bucket = os.getenv("CUTLINE_BUCKET") or os.getenv("S3_BUCKET_UPLOADS") or ""
    if not bucket:
        log.warning("cutline_no_bucket")
        return None
    prefix = os.getenv("CUTLINE_PREFIX", "aoi")
    key = f"{prefix}/{aoi}.geojson"
    try:
        body = _client().get_object(Bucket=bucket, Key=key)["Body"].read()
        return _geometry_of(json.loads(body))
    except Exception:
        log.info("cutline_boundary_unavailable key=%s", key, exc_info=True)
        return None


def _geometry_of(doc: Any) -> dict[str, Any] | None:
    """Accept a bare geometry, a Feature, or a FeatureCollection."""
    if not isinstance(doc, dict):
        return None
    kind = doc.get("type")
    if kind == "Feature":
        return _geometry_of(doc.get("geometry"))
    if kind == "FeatureCollection":
        features = doc.get("features") or []
        return _geometry_of(features[0]) if features else None
    if kind in {"Polygon", "MultiPolygon"} and doc.get("coordinates"):
        return doc
    return None


@lru_cache(maxsize=1)
def _client() -> Any:
    """One boto3 S3 client per process.

    The pod already carries the credentials GDAL reads for the rasters
    themselves, under both the AWS and the S3 spellings. The endpoint is
    taken from the full URL when there is one, and rebuilt from the host
    GDAL uses when there is not.
    """
    import boto3
    from botocore.config import Config

    endpoint = os.getenv("S3_ENDPOINT_URL") or os.getenv("AWS_S3_ENDPOINT_URL")
    if not endpoint:
        host = os.getenv("AWS_S3_ENDPOINT")
        if host:
            https = os.getenv("AWS_HTTPS", "YES").upper() in {"YES", "TRUE", "1", "ON"}
            endpoint = f"{'https' if https else 'http'}://{host}"

    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=os.getenv("AWS_DEFAULT_REGION") or os.getenv("S3_REGION") or "auto",
        config=Config(retries={"max_attempts": 2, "mode": "standard"}),
    )


def reset_caches() -> None:
    """Drop every cached boundary. For tests.

    Tolerant of a stubbed loader, so a caller can replace `_load_cached`
    and still reset in either order.
    """
    for cached in (_load_cached, _projected_cached, _client):
        clear = getattr(cached, "cache_clear", None)
        if clear is not None:
            clear()
    _local.geoms = {}
    _missing_since.clear()
