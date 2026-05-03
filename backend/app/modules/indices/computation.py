"""Pure-numpy index formulas + aggregate statistics.

This module has no I/O dependencies — every function takes ndarrays
and returns ndarrays or scalars. Rasterio reads, AOI rasterization,
and S3 writes live in the Celery task that calls these functions
(``app.modules.imagery.tasks.compute_indices``). Keeping the math
pure means the unit tests can pass tiny hand-crafted fixtures and
assert exact expected values.

Six standard indices per ARCHITECTURE.md § 9. Their canonical formulas
are seeded in ``public.indices_catalog`` (PR-A migration 0008); we
restate them here as actual numpy operations.

All inputs assumed to be FLOAT32 surface-reflectance values in 0..1
(Sentinel-2 L2A's `evalscript` already normalises to that range — see
``providers/sentinel_hub.py``). Division-by-zero is masked rather
than raising: the resulting index pixel becomes ``NaN`` and is dropped
from the valid-pixel count downstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np
from numpy.typing import NDArray

# Band names match `public.imagery_products.bands` for s2_l2a (PR-A).
# Use a Literal-ish constant rather than an enum to keep the math API
# string-based (matches `indices_catalog.code`).
BAND_BLUE = "blue"
BAND_GREEN = "green"
BAND_RED = "red"
BAND_RED_EDGE_1 = "red_edge_1"
BAND_NIR = "nir"
BAND_SWIR1 = "swir1"
BAND_SWIR2 = "swir2"

S2_L2A_BAND_ORDER: tuple[str, ...] = (
    BAND_BLUE,
    BAND_GREEN,
    BAND_RED,
    BAND_RED_EDGE_1,
    BAND_NIR,
    BAND_SWIR1,
    BAND_SWIR2,
)

# Indices supported in MVP. Order matches the catalog's seeded rows.
STANDARD_INDEX_CODES: tuple[str, ...] = ("ndvi", "ndwi", "evi", "savi", "ndre", "gndvi")


# --- Aggregate result -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class IndexAggregates:
    """Per-scene per-block per-index summary statistics.

    Fields map 1:1 to ``block_index_aggregates`` columns (data_model § 7.3).
    Decimal values are quantized to 4 fractional digits for `mean`/`min`/
    `max`/percentiles (matches `NUMERIC(7,4)`); pixel counts are int.
    """

    mean: Decimal | None
    min: Decimal | None
    max: Decimal | None
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    std_dev: Decimal | None
    valid_pixel_count: int
    total_pixel_count: int


# --- Index formulas --------------------------------------------------------


def _safe_divide(num: NDArray[Any], den: NDArray[Any]) -> NDArray[np.float32]:
    """Element-wise num/den, returning NaN where den == 0.

    Sentinel-2 L2A reflectance is non-negative; near-zero denominators
    happen at scene edges or shadowed pixels. We don't want those to
    raise or to produce ±inf — `NaN` is the standard sentinel for
    "no usable value" and downstream code already masks NaNs.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(den == 0, np.nan, num / den)
    return result.astype(np.float32, copy=False)


def ndvi(red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Vegetation Index: ``(NIR - RED) / (NIR + RED)``."""
    return _safe_divide(nir - red, nir + red)


def ndwi(green: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Water Index (McFeeters): ``(GREEN - NIR) / (GREEN + NIR)``."""
    return _safe_divide(green - nir, green + nir)


def evi(blue: NDArray[Any], red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Enhanced Vegetation Index (MODIS coefficients):

    ``2.5 * (NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1)``
    """
    num = 2.5 * (nir - red)
    den = nir + 6.0 * red - 7.5 * blue + 1.0
    return _safe_divide(num, den)


def savi(red: NDArray[Any], nir: NDArray[Any], soil_factor: float = 0.5) -> NDArray[np.float32]:
    """Soil-Adjusted Vegetation Index:

    ``(1 + L) * (NIR - RED) / (NIR + RED + L)`` where L=0.5 for moderate cover.
    """
    factor = np.float32(soil_factor)
    num = (1.0 + factor) * (nir - red)
    den = nir + red + factor
    return _safe_divide(num, den)


def ndre(red_edge_1: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Normalized Difference Red Edge: ``(NIR - RED_EDGE) / (NIR + RED_EDGE)``."""
    return _safe_divide(nir - red_edge_1, nir + red_edge_1)


def gndvi(green: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    """Green NDVI: ``(NIR - GREEN) / (NIR + GREEN)``."""
    return _safe_divide(nir - green, nir + green)


def compute_all_indices(
    bands: Mapping[str, NDArray[Any]],
) -> dict[str, NDArray[np.float32]]:
    """Compute all six standard indices from a band → array mapping.

    Missing bands raise KeyError — caller is responsible for handing in
    the full S2 L2A bandset.
    """
    return {
        "ndvi": ndvi(bands[BAND_RED], bands[BAND_NIR]),
        "ndwi": ndwi(bands[BAND_GREEN], bands[BAND_NIR]),
        "evi": evi(bands[BAND_BLUE], bands[BAND_RED], bands[BAND_NIR]),
        "savi": savi(bands[BAND_RED], bands[BAND_NIR]),
        "ndre": ndre(bands[BAND_RED_EDGE_1], bands[BAND_NIR]),
        "gndvi": gndvi(bands[BAND_GREEN], bands[BAND_NIR]),
    }


# --- Aggregation -----------------------------------------------------------


def compute_aggregates(
    index_array: NDArray[Any],
    valid_mask: NDArray[np.bool_],
) -> IndexAggregates:
    """Reduce one index raster to summary stats.

    ``valid_mask`` selects pixels inside the AOI with a usable
    reflectance value. Pixels outside the AOI or with NaN reflectance
    are excluded from `valid_pixel_count`. `total_pixel_count` is the
    AOI footprint (everything inside the polygon).

    With zero valid pixels every statistic is None — caller should
    still insert the row (the alert rule engine in PR-4 looks at
    `valid_pixel_pct` and decides what to do).
    """
    if index_array.shape != valid_mask.shape:
        raise ValueError(f"index/mask shape mismatch: {index_array.shape} vs {valid_mask.shape}")

    # `total_pixel_count` is the AOI footprint, i.e. the count of
    # pixels that COULD have been valid. We use the boolean mask shape
    # and count pixels inside the AOI; NaN pixels inside the AOI count
    # as "could-have-been-valid" but aren't.
    aoi_pixels = int(np.count_nonzero(valid_mask))
    if aoi_pixels == 0:
        return IndexAggregates(
            mean=None,
            min=None,
            max=None,
            p10=None,
            p50=None,
            p90=None,
            std_dev=None,
            valid_pixel_count=0,
            total_pixel_count=0,
        )

    # Drop NaNs from the masked subset. Both index_array and valid_mask
    # are shape-aligned 2D arrays.
    masked_values = index_array[valid_mask]
    finite = np.isfinite(masked_values)
    valid_pixel_count = int(np.count_nonzero(finite))
    if valid_pixel_count == 0:
        return IndexAggregates(
            mean=None,
            min=None,
            max=None,
            p10=None,
            p50=None,
            p90=None,
            std_dev=None,
            valid_pixel_count=0,
            total_pixel_count=aoi_pixels,
        )

    values = masked_values[finite].astype(np.float64, copy=False)
    percentiles = np.percentile(values, [10.0, 50.0, 90.0])
    return IndexAggregates(
        mean=_q4(float(values.mean())),
        min=_q4(float(values.min())),
        max=_q4(float(values.max())),
        p10=_q4(float(percentiles[0])),
        p50=_q4(float(percentiles[1])),
        p90=_q4(float(percentiles[2])),
        # ddof=0: population std-dev. The hypertable column is
        # documented as a per-scene std, not a sample estimate.
        std_dev=_q4(float(values.std(ddof=0))),
        valid_pixel_count=valid_pixel_count,
        total_pixel_count=aoi_pixels,
    )


def _q4(value: float) -> Decimal:
    """Quantize a Python float to NUMERIC(7,4) precision.

    Using Decimal here so the SQL parameter binding doesn't depend on
    floating-point rounding. The precision matches the column.
    """
    return Decimal(repr(value)).quantize(Decimal("0.0001"))
