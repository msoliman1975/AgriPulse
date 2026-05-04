"""Unit tests for the pure-numpy index formulas + aggregator."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from app.modules.indices.computation import (
    BAND_BLUE,
    BAND_GREEN,
    BAND_NIR,
    BAND_RED,
    BAND_RED_EDGE_1,
    BAND_SWIR1,
    BAND_SWIR2,
    compute_aggregates,
    compute_all_indices,
    evi,
    gndvi,
    ndre,
    ndvi,
    ndwi,
    savi,
)

# A 2x2 grid with hand-pickable reflectance values.
# Pixel (0,0): healthy vegetation     (low red, high NIR)
# Pixel (0,1): bare soil              (mid red, mid NIR)
# Pixel (1,0): water                  (very low NIR)
# Pixel (1,1): division-by-zero edge  (red+NIR == 0)
RED = np.array([[0.10, 0.20], [0.05, 0.0]], dtype=np.float32)
NIR = np.array([[0.50, 0.30], [0.02, 0.0]], dtype=np.float32)
GREEN = np.array([[0.12, 0.18], [0.10, 0.10]], dtype=np.float32)
BLUE = np.array([[0.08, 0.12], [0.06, 0.07]], dtype=np.float32)
RED_EDGE = np.array([[0.20, 0.22], [0.04, 0.05]], dtype=np.float32)


def test_ndvi_matches_hand_computation() -> None:
    result = ndvi(RED, NIR)
    # Vegetation: (0.5-0.1)/(0.5+0.1) = 0.6667
    # Bare soil:  (0.3-0.2)/(0.3+0.2) = 0.2
    # Water:      (0.02-0.05)/(0.02+0.05) = -0.4286
    # Edge:       NaN
    assert np.isclose(result[0, 0], 0.6666667, atol=1e-5)
    assert np.isclose(result[0, 1], 0.2, atol=1e-5)
    assert np.isclose(result[1, 0], -0.4285714, atol=1e-5)
    assert np.isnan(result[1, 1])


def test_ndwi_swaps_green_and_nir() -> None:
    """NDWI = (GREEN - NIR) / (GREEN + NIR) — opposite sign to NDVI for veg."""
    result = ndwi(GREEN, NIR)
    assert np.isclose(result[0, 0], (0.12 - 0.5) / (0.12 + 0.5), atol=1e-5)


def test_evi_matches_modis_formula() -> None:
    result = evi(BLUE, RED, NIR)
    # 2.5 * (0.5 - 0.1) / (0.5 + 6*0.1 - 7.5*0.08 + 1) = 1 / 1.5 ≈ 0.6667
    expected = 2.5 * (0.5 - 0.1) / (0.5 + 6 * 0.1 - 7.5 * 0.08 + 1)
    assert np.isclose(result[0, 0], expected, atol=1e-5)


def test_savi_default_l_factor() -> None:
    result = savi(RED, NIR)
    # 1.5 * (0.5 - 0.1) / (0.5 + 0.1 + 0.5) = 0.6 / 1.1 ≈ 0.5455
    expected = 1.5 * (0.5 - 0.1) / (0.5 + 0.1 + 0.5)
    assert np.isclose(result[0, 0], expected, atol=1e-5)


def test_ndre_uses_red_edge() -> None:
    result = ndre(RED_EDGE, NIR)
    expected = (0.5 - 0.2) / (0.5 + 0.2)
    assert np.isclose(result[0, 0], expected, atol=1e-5)


def test_gndvi_uses_green() -> None:
    result = gndvi(GREEN, NIR)
    expected = (0.5 - 0.12) / (0.5 + 0.12)
    assert np.isclose(result[0, 0], expected, atol=1e-5)


def test_compute_all_indices_returns_six_keys() -> None:
    bands = {
        BAND_BLUE: BLUE,
        BAND_GREEN: GREEN,
        BAND_RED: RED,
        BAND_RED_EDGE_1: RED_EDGE,
        BAND_NIR: NIR,
        BAND_SWIR1: NIR,  # SWIR isn't used by the six standard indices
        BAND_SWIR2: NIR,
    }
    result = compute_all_indices(bands)
    assert set(result.keys()) == {"ndvi", "ndwi", "evi", "savi", "ndre", "gndvi"}
    for arr in result.values():
        assert arr.shape == (2, 2)
        assert arr.dtype == np.float32


def test_compute_all_indices_missing_band_raises() -> None:
    with pytest.raises(KeyError):
        compute_all_indices({BAND_RED: RED})  # missing every other band


# --- Aggregates -----------------------------------------------------------


def test_aggregates_full_aoi_no_nans() -> None:
    """All pixels inside AOI, no NaNs — counts and stats line up."""
    values = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    mask = np.ones((2, 2), dtype=np.bool_)
    agg = compute_aggregates(values, mask)
    assert agg.total_pixel_count == 4
    assert agg.valid_pixel_count == 4
    assert agg.mean == Decimal("0.2500")
    assert agg.min == Decimal("0.1000")
    assert agg.max == Decimal("0.4000")
    # std with ddof=0: sqrt(mean((x-0.25)^2)) = sqrt(0.0125) ≈ 0.1118
    assert abs(float(agg.std_dev) - 0.111803) < 0.001


def test_aggregates_partial_mask_drops_outside_pixels() -> None:
    """Pixels outside the mask don't contribute to count or stats."""
    values = np.array([[0.1, 0.2], [99.0, 99.0]], dtype=np.float32)
    mask = np.array([[True, True], [False, False]], dtype=np.bool_)
    agg = compute_aggregates(values, mask)
    assert agg.total_pixel_count == 2
    assert agg.valid_pixel_count == 2
    # Outliers (99) outside the mask are excluded.
    assert agg.mean == Decimal("0.1500")
    assert agg.max == Decimal("0.2000")


def test_aggregates_drops_nan_pixels() -> None:
    """NaN pixels inside the AOI count toward total but not valid."""
    values = np.array([[0.1, np.nan], [0.3, 0.4]], dtype=np.float32)
    mask = np.ones((2, 2), dtype=np.bool_)
    agg = compute_aggregates(values, mask)
    assert agg.total_pixel_count == 4  # AOI-pixel count
    assert agg.valid_pixel_count == 3  # NaN excluded
    assert (
        agg.mean == Decimal((0.1 + 0.3 + 0.4) / (3).as_integer_ratio().__class__("0"))
        if False
        else agg.mean is not None
    )  # type: ignore[truthy-bool]
    # Easier: verify mean numerically.
    assert abs(float(agg.mean) - (0.1 + 0.3 + 0.4) / 3) < 1e-4


def test_aggregates_all_nan_returns_zero_valid() -> None:
    values = np.array([[np.nan, np.nan], [np.nan, np.nan]], dtype=np.float32)
    mask = np.ones((2, 2), dtype=np.bool_)
    agg = compute_aggregates(values, mask)
    assert agg.total_pixel_count == 4
    assert agg.valid_pixel_count == 0
    assert agg.mean is None
    assert agg.std_dev is None


def test_aggregates_empty_mask_returns_zeros() -> None:
    """No pixels inside the AOI — every stat is None, counts are zero."""
    values = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    mask = np.zeros((2, 2), dtype=np.bool_)
    agg = compute_aggregates(values, mask)
    assert agg.total_pixel_count == 0
    assert agg.valid_pixel_count == 0
    assert agg.mean is None


def test_aggregates_shape_mismatch_raises() -> None:
    values = np.zeros((2, 2), dtype=np.float32)
    mask = np.zeros((3, 3), dtype=np.bool_)
    with pytest.raises(ValueError, match="shape mismatch"):
        compute_aggregates(values, mask)


def test_aggregates_decimal_quantized_to_4_digits() -> None:
    """The hypertable column is NUMERIC(7,4); stats must round-trip."""
    values = np.array([[0.123456789]], dtype=np.float32)
    mask = np.ones((1, 1), dtype=np.bool_)
    agg = compute_aggregates(values, mask)
    assert agg.mean == Decimal("0.1235")  # rounded
    assert isinstance(agg.mean, Decimal)
