"""Vendored copy of the six standard-index formulas + aggregator.

Source of truth: ``backend/app/modules/indices/computation.py``. Pure numpy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import numpy as np
from numpy.typing import NDArray

STANDARD_INDEX_CODES: tuple[str, ...] = ("ndvi", "ndwi", "evi", "savi", "ndre", "gndvi")


@dataclass(frozen=True, slots=True)
class IndexAggregates:
    mean: Decimal | None
    min: Decimal | None
    max: Decimal | None
    p10: Decimal | None
    p50: Decimal | None
    p90: Decimal | None
    std_dev: Decimal | None
    valid_pixel_count: int
    total_pixel_count: int


def _safe_divide(num: NDArray[Any], den: NDArray[Any]) -> NDArray[np.float32]:
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(den == 0, np.nan, num / den)
    return result.astype(np.float32, copy=False)


def ndvi(red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    return _safe_divide(nir - red, nir + red)


def ndwi(green: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    return _safe_divide(green - nir, green + nir)


def evi(blue: NDArray[Any], red: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    num = 2.5 * (nir - red)
    den = nir + 6.0 * red - 7.5 * blue + 1.0
    return _safe_divide(num, den)


def savi(red: NDArray[Any], nir: NDArray[Any], soil_factor: float = 0.5) -> NDArray[np.float32]:
    factor = np.float32(soil_factor)
    num = (1.0 + factor) * (nir - red)
    den = nir + red + factor
    return _safe_divide(num, den)


def ndre(red_edge_1: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    return _safe_divide(nir - red_edge_1, nir + red_edge_1)


def gndvi(green: NDArray[Any], nir: NDArray[Any]) -> NDArray[np.float32]:
    return _safe_divide(nir - green, nir + green)


def compute_all_indices(bands: Mapping[str, NDArray[Any]]) -> dict[str, NDArray[np.float32]]:
    return {
        "ndvi": ndvi(bands["red"], bands["nir"]),
        "ndwi": ndwi(bands["green"], bands["nir"]),
        "evi": evi(bands["blue"], bands["red"], bands["nir"]),
        "savi": savi(bands["red"], bands["nir"]),
        "ndre": ndre(bands["red_edge_1"], bands["nir"]),
        "gndvi": gndvi(bands["green"], bands["nir"]),
    }


def compute_aggregates(
    index_array: NDArray[Any],
    valid_mask: NDArray[np.bool_],
) -> IndexAggregates:
    if index_array.shape != valid_mask.shape:
        raise ValueError(f"index/mask shape mismatch: {index_array.shape} vs {valid_mask.shape}")

    aoi_pixels = int(np.count_nonzero(valid_mask))
    if aoi_pixels == 0:
        return IndexAggregates(None, None, None, None, None, None, None, 0, 0)

    masked = index_array[valid_mask]
    # Numerical edge cases (e.g. EVI denominator near zero on saturated/dark
    # pixels) can produce values in the thousands. The DB column is
    # NUMERIC(7,4) — abs(value) >= 1000 overflows. Treat values outside a
    # physically-plausible window as outliers; standard vegetation/water
    # indices saturate well inside [-10, 10].
    masked = np.where(np.abs(masked) > 10.0, np.nan, masked)
    finite = np.isfinite(masked)
    valid_pixel_count = int(np.count_nonzero(finite))
    if valid_pixel_count == 0:
        return IndexAggregates(None, None, None, None, None, None, None, 0, aoi_pixels)

    values = masked[finite].astype(np.float64, copy=False)
    p10, p50, p90 = np.percentile(values, [10.0, 50.0, 90.0])
    return IndexAggregates(
        mean=_q4(float(values.mean())),
        min=_q4(float(values.min())),
        max=_q4(float(values.max())),
        p10=_q4(float(p10)),
        p50=_q4(float(p50)),
        p90=_q4(float(p90)),
        std_dev=_q4(float(values.std(ddof=0))),
        valid_pixel_count=valid_pixel_count,
        total_pixel_count=aoi_pixels,
    )


def _q4(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal("0.0001"))
