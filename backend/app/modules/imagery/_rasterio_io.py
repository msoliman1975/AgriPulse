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
    compute_indices_for_product,
    quality_band_mask,
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
    aoi_geojson_utm: dict[str, Any],
    product_code: str = "s2_l2a",
    all_touched: bool = True,
) -> tuple[
    dict[str, NDArray[np.float32]],
    NDArray[np.bool_],
    NDArray[np.bool_],
    dict[str, Any],
]:
    """Read every band into memory + rasterise the AOI mask + cloud mask.

    Returns ``(bands_arrays, aoi_mask, cloud_mask, profile)`` where
    ``profile`` is a rasterio profile suitable for re-using as the per-index
    COG write profile (count=1, dtype=float32).

    ``band_names`` lists the *science* bands. A raw COG may carry one extra
    trailing band — the quality band the provider appends when cloud masking
    is enabled (SCL for Sentinel-2, QA_PIXEL for Landsat). When present,
    ``cloud_mask`` is True over cloud/shadow/cirrus/snow/invalid pixels;
    otherwise it is all-False, so pre-SCL COGs (and masking-disabled
    fetches) aggregate exactly as before.

    ``product_code`` selects which masking rules that trailing band follows.
    It defaults to ``s2_l2a`` so existing callers are unchanged, but the two
    encodings are not interchangeable: SCL is a class enum and QA_PIXEL is a
    bitmask, so reading one with the other's rules produces a
    plausible-looking mask that is entirely wrong.

    ``aoi_geojson_utm`` must be in the raw COG's own CRS. That is the farm's
    UTM zone (`farms.utm_srid`), not a fixed one — the mask is rasterised
    against the dataset transform, so a mismatch masks the wrong pixels
    without raising.

    ``all_touched`` picks the rule for "is this pixel inside the AOI".

    True — the default and what the per-block path has always used — keeps
    any pixel whose footprint TOUCHES the boundary. It loses no edge data,
    and the block aggregates in the database were all measured under it, so
    changing it there would put a step in every block's history.

    False keeps only pixels whose CENTRE falls inside, which is what the FARM
    surface uses. That raster is drawn on a map against the farm's own
    outline, and under the touched rule it paints up to a full pixel of
    colour past the border — 10 m for Sentinel-2, 30 m for Landsat, a visible
    staircase around a smooth boundary, and the same fringe that inflates the
    legend's covered area by ~2%. A farm is never thinner than a pixel, so
    the centre rule cannot empty it; a narrow BLOCK could vanish under it,
    which is the other half of why the default stays True.
    """
    n_science = len(band_names)
    with _gdal_s3_env(), rasterio.open(raw_uri) as ds:
        if ds.count not in (n_science, n_science + 1):
            raise ValueError(
                f"raw COG has {ds.count} bands; expected {n_science} or "
                f"{n_science + 1} (science bands {band_names!r} + optional "
                f"quality band)"
            )
        bands_arrays = {
            name: ds.read(idx + 1).astype(np.float32, copy=False)
            for idx, name in enumerate(band_names)
        }
        if ds.count == n_science + 1:
            quality = ds.read(n_science + 1).astype(np.float32, copy=False)
            cloud_mask = quality_band_mask(product_code, quality)
        else:
            cloud_mask = np.zeros((ds.height, ds.width), dtype=bool)
        geom = shape(aoi_geojson_utm)
        aoi_mask = ~geometry_mask(
            [geom],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=all_touched,
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
    return bands_arrays, aoi_mask, cloud_mask, write_profile


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
    cloud_mask: NDArray[np.bool_] | None = None,
    air_temp_c: float | None = None,
) -> tuple[
    dict[str, IndexAggregates],
    dict[str, str],
    dict[str, NDArray[np.float32]],
]:
    """Compute the product's indices, upload each as a COG, return
    aggregates + keys + the AOI-masked rasters themselves.

    Which indices get computed follows ``product_code``: the nine
    Sentinel-2 ones for ``s2_l2a``, the three thermal ones for
    ``landsat_c2_l2_st``.

    The third return value (``index_rasters``) is the AOI-masked
    per-index arrays kept in memory so the caller can run additional
    zonal stats (sub-block grid cells, custom AOIs) without re-reading
    from S3. Outside the AOI is NaN — matches what was written to the
    COG. Order matches the catalog (ndvi → gndvi; lst → smi).

    ``cloud_mask`` (True over cloud/shadow/etc., from the quality band)
    turns those pixels into NaN *before* aggregation and writing. They stay
    inside the AOI footprint (``total_pixel_count``) but drop out of
    ``valid_pixel_count``, so ``valid_pixel_pct`` reflects the real clear
    fraction, and per-cell grid stats inherit the masking for free.

    ``air_temp_c`` is only read for the thermal product, where CWSI needs
    it. Leaving it None there costs CWSI alone — LST and SMI still
    compute, so a missing weather hour does not cost the whole scene.
    """
    indices = compute_indices_for_product(product_code, bands_arrays, air_temp_c=air_temp_c)
    has_cloud = cloud_mask is not None and bool(cloud_mask.any())
    aggregates: dict[str, IndexAggregates] = {}
    written_keys: dict[str, str] = {}
    masked_rasters: dict[str, NDArray[np.float32]] = {}

    for index_code, raster in indices.items():
        # Cloud/shadow pixels → NaN before any stats so they fall out of
        # valid_pixel_count (but stay in the AOI footprint total).
        clouded = (
            np.where(cloud_mask, np.float32("nan"), raster)
            if has_cloud and cloud_mask is not None
            else raster
        )
        aggregates[index_code] = compute_aggregates(clouded, aoi_mask)
        # Apply the AOI mask to the raster before writing. NaN outside
        # the AOI keeps tile-server rendering clean and lets downstream
        # zonal stats ignore the off-AOI region without re-masking.
        out_array = np.where(aoi_mask, clouded, np.float32("nan"))
        masked_rasters[index_code] = out_array

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

    return aggregates, written_keys, masked_rasters


# Suppress unused-import warning when only re-exported.
_ = io
