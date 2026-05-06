"""Rasterio-driven IO for the compute_indices task.

Two functions:

  * ``load_raw_bands_and_aggregate`` reads the multi-band raw COG from
    S3, extracts each band as a numpy array, and rasterizes the AOI
    polygon onto the raster's grid.
  * ``compute_and_write_indices`` invokes the pure-numpy index
    formulas from `computation.py`, then writes each per-index COG to
    object storage at the deterministic key. Returns the per-index
    aggregate stats AND the S3 keys it wrote, so the caller can
    update the pgstac item assets.

Module loaded only inside the heavy-queue worker — keeps rasterio /
shapely off the import path of the API and the light worker.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.profiles import default_gtiff_profile
from rasterio.session import AWSSession
from shapely.geometry import shape

from app.core.settings import get_settings
from app.modules.imagery.storage import build_asset_key
from app.modules.indices.computation import (
    IndexAggregates,
    compute_aggregates,
    compute_all_indices,
)
from app.shared.storage import StorageClient


@contextmanager
def _gdal_s3_env() -> Iterator[None]:
    """Configure GDAL's ``/vsis3/`` driver from our boto3-style settings.

    Rasterio refuses to accept ``AWS_*`` keyword arguments to
    ``rasterio.Env`` when boto3 is installed — it raises
    "GDAL's AWS config options can not be directly set". Auth has to
    flow through ``rasterio.session.AWSSession``; the *endpoint* knobs
    (``AWS_S3_ENDPOINT``, ``AWS_HTTPS``, ``AWS_VIRTUAL_HOSTING``) still
    have to reach GDAL, and the cleanest way is via the process env.
    We restore the prior values on exit so this stays hermetic.
    """
    settings = get_settings()
    extras: dict[str, str] = {}
    if settings.s3_endpoint_url:
        scheme, _, host = settings.s3_endpoint_url.partition("://")
        if not host:
            host = scheme
            scheme = "https"
        extras["AWS_S3_ENDPOINT"] = host
        extras["AWS_HTTPS"] = "YES" if scheme == "https" else "NO"
    extras["AWS_VIRTUAL_HOSTING"] = "FALSE" if settings.s3_path_style else "TRUE"
    extras["AWS_REGION"] = settings.s3_region

    saved = {k: os.environ.get(k) for k in extras}
    os.environ.update(extras)
    try:
        session = AWSSession(
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )
        with rasterio.Env(session=session):
            yield
    finally:
        for key, prior in saved.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


def load_raw_bands_and_aggregate(
    raw_uri: str,
    *,
    band_names: tuple[str, ...],
    aoi_geojson_utm36n: dict[str, Any],
) -> tuple[dict[str, NDArray[np.float32]], NDArray[np.bool_], dict[str, Any]]:
    """Read every band into memory + rasterise the AOI mask.

    Returns ``(bands_arrays, aoi_mask, profile)`` where ``profile`` is
    a rasterio profile suitable for re-using as the per-index COG
    write profile (count=1, dtype=float32).
    """
    with _gdal_s3_env(), rasterio.open(raw_uri) as ds:
        if ds.count != len(band_names):
            raise ValueError(
                f"raw COG has {ds.count} bands; expected {len(band_names)} " f"({band_names!r})"
            )
        bands_arrays = {
            name: ds.read(idx + 1).astype(np.float32, copy=False)
            for idx, name in enumerate(band_names)
        }
        geom = shape(aoi_geojson_utm36n)
        aoi_mask = ~geometry_mask(
            [geom],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=True,
        )
        base_profile = ds.profile.copy()

    # Per-index COGs are single-band float32 in the raw COG's CRS/grid.
    # Borrow the source profile and tighten count + dtype + COG hints.
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
    }
    # default_gtiff_profile contributes BIGTIFF/INTERLEAVE defaults.
    write_profile = {**default_gtiff_profile, **write_profile}
    return bands_arrays, aoi_mask, write_profile


def compute_and_write_indices(
    *,
    bands_arrays: dict[str, NDArray[np.float32]],
    aoi_mask: NDArray[np.bool_],
    profile: dict[str, Any],
    storage: StorageClient,
    provider_code: str,
    product_code: str,
    scene_id: str,
    aoi_hash: str,
) -> tuple[dict[str, IndexAggregates], dict[str, str]]:
    """Compute six indices, upload each as a COG, return aggregates + keys.

    The returned ``index_aggregates`` map preserves insertion order
    (the catalog order: ndvi → gndvi); the matching ``index_keys`` map
    holds the S3 key each per-index COG was written to.
    """
    indices = compute_all_indices(bands_arrays)
    aggregates: dict[str, IndexAggregates] = {}
    written_keys: dict[str, str] = {}

    for index_code, raster in indices.items():
        aggregates[index_code] = compute_aggregates(raster, aoi_mask)
        # Apply the AOI mask to the raster before writing. NaN outside
        # the AOI keeps tile-server rendering clean.
        out_array = np.where(aoi_mask, raster, np.float32("nan"))

        # Write to an in-memory GeoTIFF (COG profile) and upload.
        with MemoryFile() as memfile:
            with memfile.open(**profile) as dst:
                dst.write(out_array, 1)
            cog_bytes = memfile.read()

        key = build_asset_key(
            provider_code=provider_code,
            product_code=product_code,
            scene_id=scene_id,
            aoi_hash=aoi_hash,
            band_or_index=index_code,
        )
        storage.put_object(
            key=key,
            body=cog_bytes,
            content_type="image/tiff; application=geotiff; profile=cloud-optimized",
        )
        written_keys[index_code] = key

    return aggregates, written_keys


# Suppress unused-import warning when only re-exported.
_ = io
