"""Per-pixel explanation of an index value.

The point of this module is that it must be *impossible* for it to disagree
with the pipeline. It therefore borrows rather than reimplements:

  * the index maths comes from ``indices.computation.compute_all_indices``;
  * the mask decision comes from ``indices.computation.scl_cloud_mask``;
  * the asset path comes from ``imagery.storage.build_asset_key``;
  * the GDAL/S3 credential wiring comes from imagery's rasterio helper.

The only thing written here is the *rendering* — turning the catalog's
``formula_text`` into a substituted expression — and even that pulls the
formula string from ``public.indices_catalog`` rather than restating it, so
there is no second copy of any formula anywhere in this file.

Reading one pixel is a single GDAL range request against the COG. That is
fast enough to answer a click without a job queue, which is why this lives
in the API process rather than behind Celery.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window
from shapely.geometry import box, shape

# Private helper by name, public boundary in fact: it is the single place the
# app configures GDAL's /vsis3 driver from our S3 settings. Copying it here
# would give us a second credential path to keep in step with the first —
# exactly the silent drift Observer exists to surface.
from app.modules.imagery._rasterio_io import _gdal_s3_env
from app.modules.indices.computation import (
    STANDARD_INDEX_CODES,
    compute_all_indices,
    scl_cloud_mask,
)

# Sentinel-2 SCL class meanings, for the mask verdict. Values match
# `S2_SCL_MASKED_CLASSES` in indices.computation, which stays the authority
# on *which* are dropped — this table only supplies the human label.
SCL_LABELS: dict[int, str] = {
    0: "no data",
    1: "saturated or defective",
    2: "dark area pixels",
    3: "cloud shadow",
    4: "vegetation",
    5: "bare soil",
    6: "water",
    7: "unclassified",
    8: "cloud, medium probability",
    9: "cloud, high probability",
    10: "thin cirrus",
    11: "snow or ice",
}

# Catalog `formula_text` writes bands in prose ("NIR", "RedEdge"); the arrays
# are keyed by the product's band names. This is the only mapping between the
# two, and `test_formula_tokens_cover_every_catalog_formula` pins it.
FORMULA_TOKEN_TO_BAND: dict[str, str] = {
    "Blue": "blue",
    "Green": "green",
    "Red": "red",
    "RedEdge": "red_edge_1",
    "NIR": "nir",
    "SWIR1": "swir1",
    "SWIR2": "swir2",
    # Landsat thermal (`landsat_c2_l2_st`). Arrives in kelvin, so `lst`'s
    # catalog formula is just the unit conversion. A Sentinel-2 scene has
    # no such band, so `substitute_formula` returns None there — which is
    # the same "this product cannot compute this index" path NDMI takes on
    # PlanetScope.
    "LWIR11": "lwir11",
}

# Longest first, so "SWIR1" is not consumed by a shorter prefix and "RedEdge"
# is not split into "Red" + "Edge".
_TOKEN_RE = re.compile(
    "|".join(sorted((re.escape(k) for k in FORMULA_TOKEN_TO_BAND), key=len, reverse=True))
)


class PixelOutsideRasterError(Exception):
    """The requested coordinate falls outside the scene's raster."""


class RawAssetMissingError(Exception):
    """The raw-bands COG for this scene is not in object storage."""


@dataclass(frozen=True, slots=True)
class PixelExplanation:
    row: int
    col: int
    lon: float
    lat: float
    inside_aoi: bool
    band_values: dict[str, float | None]
    scl_value: int | None
    scl_label: str | None
    masked: bool
    mask_reason: str | None
    indices: dict[str, dict[str, Any]]
    unavailable_indices: dict[str, str]


def substitute_formula(formula_text: str, band_values: dict[str, float | None]) -> str | None:
    """Render a catalog formula with this pixel's numbers in place of names.

    Returns None when the formula references a band the product does not
    carry — a PlanetScope scene has no SWIR1, and printing an expression with
    a hole in it would be worse than printing nothing.
    """
    missing = False

    def _sub(match: re.Match[str]) -> str:
        nonlocal missing
        band = FORMULA_TOKEN_TO_BAND[match.group(0)]
        value = band_values.get(band)
        if value is None:
            missing = True
            return match.group(0)
        return f"{value:.4f}"

    rendered = _TOKEN_RE.sub(_sub, formula_text)
    return None if missing else rendered


def _exclusion_reason(
    *,
    masked: bool,
    mask_reason: str | None,
    inside_aoi: bool,
    value: float | None,
) -> str | None:
    """Why this pixel contributed nothing, or None if it contributed.

    Ordered the way the pipeline drops pixels: outside the AOI it is never
    read at all, inside it the cloud mask runs before the arithmetic, and a
    non-finite result is what is left. Reporting them in a different order
    would name a cause that was never reached.
    """
    if not inside_aoi:
        return "outside the block boundary"
    if masked:
        return mask_reason
    if value is None:
        return "no usable value (sensor gap or divide-by-zero)"
    return None


def explain_pixel(
    *,
    raw_uri: str,
    band_names: tuple[str, ...],
    supported_indices: tuple[str, ...],
    aoi_geojson_utm: dict[str, Any],
    lon: float,
    lat: float,
    formulas: dict[str, str],
) -> PixelExplanation:
    """Read one pixel from the raw-bands COG and explain every index on it.

    ``supported_indices`` comes from ``imagery_products``, so a product with
    no SWIR simply never offers NDMI rather than offering it and failing —
    the inspector degrades with the product instead of assuming Sentinel-2.
    """
    with _gdal_s3_env(), rasterio.open(raw_uri) as ds:
        # The COG is in a metre-based projection; a map click is lon/lat.
        xs, ys = warp_transform("EPSG:4326", ds.crs, [lon], [lat])
        x, y = float(xs[0]), float(ys[0])
        row, col = ds.index(x, y)
        if not (0 <= row < ds.height and 0 <= col < ds.width):
            raise PixelOutsideRasterError(f"({lon}, {lat}) is outside this scene's raster")

        window = Window(col_off=col, row_off=row, width=1, height=1)
        stack = ds.read(window=window).astype(np.float32, copy=False)
        n_science = len(band_names)
        has_scl = ds.count == n_science + 1
        pixel_bounds = rasterio.windows.bounds(window, ds.transform)

    values: dict[str, float | None] = {}
    for idx, name in enumerate(band_names):
        raw = float(stack[idx, 0, 0])
        values[name] = None if not np.isfinite(raw) else raw

    scl_value: int | None = None
    scl_label: str | None = None
    masked = False
    mask_reason: str | None = None
    if has_scl:
        scl_raw = stack[n_science, 0, 0]
        scl_value = int(np.rint(float(scl_raw)))
        scl_label = SCL_LABELS.get(scl_value, "unknown class")
        # Ask the pipeline's own predicate rather than re-listing the classes.
        masked = bool(scl_cloud_mask(np.array([[scl_raw]]))[0, 0])
        if masked:
            mask_reason = f"SCL = {scl_value} ({scl_label})"

    # `all_touched=True` is what the pipeline rasterises the AOI with, so a
    # pixel counts as inside when its footprint *intersects* the boundary —
    # not when its centre is contained. Testing containment here would
    # disagree with the aggregate along every edge of the block.
    inside_aoi = bool(shape(aoi_geojson_utm).intersects(box(*pixel_bounds)))

    indices: dict[str, dict[str, Any]] = {}
    unavailable: dict[str, str] = {}

    arrays: dict[str, NDArray[np.float32]] = {
        name: np.array([[values[name] if values[name] is not None else np.nan]], dtype=np.float32)
        for name in band_names
    }
    computable = [c for c in supported_indices if c in STANDARD_INDEX_CODES]
    try:
        computed = compute_all_indices(arrays)
    except KeyError:
        # The product is missing a band one of the standard formulas needs.
        # Fall back to per-index reporting so the ones that *can* be computed
        # still are, instead of the whole panel failing.
        computed = {}

    for code in STANDARD_INDEX_CODES:
        formula = formulas.get(code)
        if code not in computable:
            unavailable[code] = "not offered by this product"
            continue
        if code not in computed:
            unavailable[code] = "requires a band this product does not carry"
            continue
        raw_value = float(computed[code][0, 0])
        value = None if not np.isfinite(raw_value) else raw_value
        indices[code] = {
            "value": None if masked or not inside_aoi else value,
            "raw_value": value,
            "formula_text": formula,
            "substituted": substitute_formula(formula, values) if formula else None,
            # Says *why* a pixel contributes nothing, which is the question a
            # low valid-pixel percentage actually raises.
            "excluded_reason": _exclusion_reason(
                masked=masked,
                mask_reason=mask_reason,
                inside_aoi=inside_aoi,
                value=value,
            ),
        }

    return PixelExplanation(
        row=int(row),
        col=int(col),
        lon=lon,
        lat=lat,
        inside_aoi=inside_aoi,
        band_values=values,
        scl_value=scl_value,
        scl_label=scl_label,
        masked=masked,
        mask_reason=mask_reason,
        indices=indices,
        unavailable_indices=unavailable,
    )


@dataclass(frozen=True, slots=True)
class PixelBudget:
    """Where a scene's pixels went, per index.

    The database stores only `valid_pixel_count` and `total_pixel_count`, so
    "why is this 43% valid?" is unanswerable from it — cloud-masked and
    no-data pixels are indistinguishable once counted. This recomputes the
    split from the COG. OBS-5 persists it so the read stops being necessary.
    """

    aoi_pixel_count: int
    masked_pixel_count: int
    per_index: dict[str, dict[str, int]]


def compute_pixel_budget(
    *,
    raw_uri: str,
    band_names: tuple[str, ...],
    supported_indices: tuple[str, ...],
    aoi_geojson_utm: dict[str, Any],
) -> PixelBudget:
    """Reconcile AOI footprint → SCL-masked → no-data → valid, per index."""
    from rasterio.features import geometry_mask

    with _gdal_s3_env(), rasterio.open(raw_uri) as ds:
        n_science = len(band_names)
        arrays = {
            name: ds.read(idx + 1).astype(np.float32, copy=False)
            for idx, name in enumerate(band_names)
        }
        if ds.count == n_science + 1:
            cloud_mask = scl_cloud_mask(ds.read(n_science + 1).astype(np.float32, copy=False))
        else:
            cloud_mask = np.zeros((ds.height, ds.width), dtype=bool)
        aoi_mask = ~geometry_mask(
            [shape(aoi_geojson_utm)],
            out_shape=(ds.height, ds.width),
            transform=ds.transform,
            invert=False,
            all_touched=True,
        )

    aoi_pixels = int(np.count_nonzero(aoi_mask))
    masked_in_aoi = int(np.count_nonzero(cloud_mask & aoi_mask))

    per_index: dict[str, dict[str, int]] = {}
    try:
        computed = compute_all_indices(arrays)
    except KeyError:
        computed = {}

    for code, raster in computed.items():
        if code not in supported_indices:
            continue
        clouded = np.where(cloud_mask, np.float32("nan"), raster)
        in_aoi = clouded[aoi_mask]
        valid = int(np.count_nonzero(np.isfinite(in_aoi)))
        per_index[code] = {
            "aoi": aoi_pixels,
            "masked": masked_in_aoi,
            # Everything inside the AOI that survived masking but still has no
            # number: sensor gaps and divide-by-zero in this index's formula.
            "nodata": aoi_pixels - masked_in_aoi - valid,
            "valid": valid,
        }

    return PixelBudget(
        aoi_pixel_count=aoi_pixels,
        masked_pixel_count=masked_in_aoi,
        per_index=per_index,
    )
