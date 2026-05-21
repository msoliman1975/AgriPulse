"""Rasterio reads + writes — local-disk only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.profiles import default_gtiff_profile
from shapely.geometry import shape


def write_raw_bands_tif(path: Path, cog_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cog_bytes)


def load_bands_and_mask(
    raw_tif_path: Path,
    *,
    band_names: tuple[str, ...],
    aoi_geojson_utm: dict[str, Any],
) -> tuple[dict[str, NDArray[np.float32]], NDArray[np.bool_], dict[str, Any]]:
    with rasterio.open(raw_tif_path) as ds:
        if ds.count != len(band_names):
            raise ValueError(
                f"{raw_tif_path}: raw TIFF has {ds.count} bands; expected {len(band_names)} "
                f"({band_names!r})"
            )
        bands_arrays = {
            name: ds.read(idx + 1).astype(np.float32, copy=False)
            for idx, name in enumerate(band_names)
        }
        geom = shape(aoi_geojson_utm)
        aoi_mask = ~geometry_mask(
            [geom],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=True,
        )
        base_profile = ds.profile.copy()

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
    write_profile = {**default_gtiff_profile, **write_profile}
    return bands_arrays, aoi_mask, write_profile


def write_index_cog_bytes(
    *,
    index_array: NDArray[np.float32],
    aoi_mask: NDArray[np.bool_],
    profile: dict[str, Any],
) -> bytes:
    """Mask + serialize a single-band index COG to bytes (for direct S3 upload)."""
    out_array = np.where(aoi_mask, index_array, np.float32("nan"))
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dst:
            dst.write(out_array, 1)
        return memfile.read()


def write_index_cog(
    path: Path,
    *,
    index_array: NDArray[np.float32],
    aoi_mask: NDArray[np.bool_],
    profile: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        write_index_cog_bytes(index_array=index_array, aoi_mask=aoi_mask, profile=profile)
    )
