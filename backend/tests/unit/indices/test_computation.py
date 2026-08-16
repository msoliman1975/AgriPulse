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
    S2_SCL_MASKED_CLASSES,
    STANDARD_INDEX_CODES,
    bsi,
    compute_aggregates,
    compute_all_indices,
    evi,
    gndvi,
    msavi,
    msi,
    ndmi,
    ndre,
    ndvi,
    ndwi,
    savi,
    scl_cloud_mask,
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


def test_scl_cloud_mask_flags_cloud_classes_only() -> None:
    # One pixel per SCL class 0..11 (float32, as it arrives in the COG).
    scl = np.arange(12, dtype=np.float32).reshape(3, 4)
    mask = scl_cloud_mask(scl)
    flagged = {int(v) for v in scl[mask]}
    assert flagged == set(S2_SCL_MASKED_CLASSES)
    # Clear land/water classes must NOT be masked.
    assert not mask[scl == 4.0]  # vegetation
    assert not mask[scl == 5.0]  # bare soil
    assert not mask[scl == 6.0]  # water


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


def test_msavi_matches_the_msavi2_closed_form() -> None:
    """MSAVI2 = (2*NIR + 1 - sqrt((2*NIR + 1)^2 - 8*(NIR - RED))) / 2."""
    result = msavi(RED, NIR)

    def expected(red: float, nir: float) -> float:
        a = 2.0 * nir + 1.0
        return (a - (a**2 - 8.0 * (nir - red)) ** 0.5) / 2.0

    assert np.isclose(result[0, 0], expected(0.10, 0.50), atol=1e-5)
    assert np.isclose(result[0, 1], expected(0.20, 0.30), atol=1e-5)
    assert np.isclose(result[1, 0], expected(0.05, 0.02), atol=1e-5)


def test_msavi_is_finite_where_ndvi_divides_by_zero() -> None:
    """The fixture's red + NIR == 0 pixel is NaN for NDVI but 0.0 here.

    MSAVI2 has no denominator that can vanish — the `/ 2` is a constant — so
    the zero-reflectance pixel is a real reading of zero rather than a gap.
    That is not a missing mask: nodata reaches these formulas as NaN (the
    COG's nodata value, see `imagery/_rasterio_io.py`), never as 0.0, so
    masking zeros here would discard honest dark pixels.
    """
    assert np.isnan(ndvi(RED, NIR)[1, 1])
    assert np.isclose(msavi(RED, NIR)[1, 1], 0.0, atol=1e-6)
    # A genuine gap still propagates.
    gap = np.array([[np.nan]], dtype=np.float32)
    assert np.isnan(msavi(gap, np.array([[0.4]], dtype=np.float32))[0, 0])


def test_msavi_tracks_savi_rather_than_ndvi() -> None:
    """Why it shares SAVI's class boundaries downstream and not NDVI's.

    MSAVI2 solves for the soil factor per pixel instead of pinning L = 0.5,
    so it lands near SAVI and materially below NDVI wherever soil is still
    in the pixel. Downstream, `indexClasses.ts` reads MSAVI on the
    soil-adjusted scale on the strength of this — if a formula edit ever
    moved it onto NDVI's magnitude, every legend would silently mis-class.
    """
    rng = np.random.default_rng(20260816)
    shape = (64, 64)
    # Physical orchard-over-sand reflectance: red 0.02-0.32, NIR 0.05-0.55.
    red = (rng.random(shape, dtype=np.float32) * 0.30 + 0.02).astype(np.float32)
    nir = (rng.random(shape, dtype=np.float32) * 0.50 + 0.05).astype(np.float32)

    m = msavi(red, nir)
    s = savi(red, nir)
    n = ndvi(red, nir)
    vegetated = n > 0.2  # below that everything converges on zero and proves nothing

    assert np.abs(m - s)[vegetated].max() < 0.10
    assert np.abs(m - n)[vegetated].mean() > np.abs(m - s)[vegetated].mean()


def test_msavi_stays_within_the_normalized_range() -> None:
    """Bounded to [-1, 1] like the normalized differences, unlike `msi`."""
    rng = np.random.default_rng(20260816)
    shape = (64, 64)
    red = rng.random(shape, dtype=np.float32)
    nir = rng.random(shape, dtype=np.float32)
    result = msavi(red, nir)
    finite = result[np.isfinite(result)]
    assert finite.size == result.size  # the discriminant cannot go negative here
    assert finite.min() >= -1.0
    assert finite.max() <= 1.0


def test_ndre_uses_red_edge() -> None:
    result = ndre(RED_EDGE, NIR)
    expected = (0.5 - 0.2) / (0.5 + 0.2)
    assert np.isclose(result[0, 0], expected, atol=1e-5)


def test_gndvi_uses_green() -> None:
    result = gndvi(GREEN, NIR)
    expected = (0.5 - 0.12) / (0.5 + 0.12)
    assert np.isclose(result[0, 0], expected, atol=1e-5)


def test_ndmi_uses_nir_and_swir1() -> None:
    """NDMI = (NIR - SWIR1) / (NIR + SWIR1); leaf-moisture, not surface water."""
    swir1 = np.array([[0.30, 0.25], [0.10, 0.0]], dtype=np.float32)
    result = ndmi(NIR, swir1)
    assert np.isclose(result[0, 0], (0.50 - 0.30) / (0.50 + 0.30), atol=1e-5)  # 0.25
    assert np.isclose(result[0, 1], (0.30 - 0.25) / (0.30 + 0.25), atol=1e-5)
    assert np.isclose(result[1, 0], (0.02 - 0.10) / (0.02 + 0.10), atol=1e-5)
    assert np.isnan(result[1, 1])  # NIR + SWIR1 == 0 → masked


def test_bsi_weighs_soil_bands_against_vegetation_bands() -> None:
    """BSI = ((SWIR1+RED) - (NIR+BLUE)) / ((SWIR1+RED) + (NIR+BLUE))."""
    swir1 = np.array([[0.30, 0.25], [0.10, 0.0]], dtype=np.float32)
    result = bsi(BLUE, RED, NIR, swir1)
    # (0,0) healthy canopy: NIR+BLUE (0.58) dominates SWIR1+RED (0.40) → negative.
    assert np.isclose(result[0, 0], (0.40 - 0.58) / (0.40 + 0.58), atol=1e-5)
    assert result[0, 0] < 0
    # (0,1) bare-soil pixel: SWIR1+RED (0.45) beats NIR+BLUE (0.42) → positive.
    assert np.isclose(result[0, 1], (0.45 - 0.42) / (0.45 + 0.42), atol=1e-5)
    assert result[0, 1] > 0
    assert np.isclose(result[1, 0], (0.15 - 0.08) / (0.15 + 0.08), atol=1e-5)
    # (1,1) is the fixture's red+NIR == 0 pixel, which masks NDVI to NaN. BSI
    # survives it, because blue (0.07) keeps the denominator non-zero — so the
    # four-band form degrades to a real -1.0 where the two-band indices give up.
    assert np.isclose(result[1, 1], -1.0, atol=1e-5)


def test_bsi_masks_only_when_all_four_bands_vanish() -> None:
    """The NaN case for BSI needs every contributing band at zero."""
    zeros = np.zeros((1, 1), dtype=np.float32)
    assert np.isnan(bsi(zeros, zeros, zeros, zeros)[0, 0])


def test_bsi_stays_within_normalized_difference_range() -> None:
    """BSI is a normalized difference, so it cannot leave [-1, 1]."""
    rng = np.random.default_rng(20260812)
    shape = (32, 32)
    values = [rng.random(shape, dtype=np.float32) for _ in range(4)]
    result = bsi(*values)
    finite = result[np.isfinite(result)]
    assert finite.min() >= -1.0
    assert finite.max() <= 1.0


def test_msi_is_a_ratio_not_a_normalized_difference() -> None:
    """MSI = SWIR1 / NIR — unbounded above, and inverted vs every other index."""
    swir1 = np.array([[0.30, 0.25], [0.10, 0.0]], dtype=np.float32)
    result = msi(NIR, swir1)
    assert np.isclose(result[0, 0], 0.30 / 0.50, atol=1e-5)  # 0.60
    assert np.isclose(result[0, 1], 0.25 / 0.30, atol=1e-5)  # 0.833…
    # (1,0) is the water pixel: NIR collapses to 0.02, so the ratio blows past
    # 1.0. This is the case that breaks any [-1, 1] clamp downstream.
    assert np.isclose(result[1, 0], 0.10 / 0.02, atol=1e-5)  # 5.0
    assert result[1, 0] > 1.0
    assert np.isnan(result[1, 1])  # NIR == 0 → masked


def test_msi_is_the_monotone_inverse_of_ndmi() -> None:
    """ndmi == (1 - msi) / (1 + msi).

    Pins the documented relationship between the two, so that if either
    formula is ever edited the drift shows up here rather than as two trend
    lines that quietly disagree.
    """
    rng = np.random.default_rng(20260812)
    shape = (16, 16)
    # Offset away from zero so neither denominator is masked.
    nir = rng.random(shape, dtype=np.float32) * 0.8 + 0.1
    swir1 = rng.random(shape, dtype=np.float32) * 0.8 + 0.1

    m = msi(nir, swir1)
    expected_ndmi = (1.0 - m) / (1.0 + m)
    assert np.allclose(ndmi(nir, swir1), expected_ndmi, atol=1e-5)


def test_compute_all_indices_returns_every_standard_code() -> None:
    bands = {
        BAND_BLUE: BLUE,
        BAND_GREEN: GREEN,
        BAND_RED: RED,
        BAND_RED_EDGE_1: RED_EDGE,
        BAND_NIR: NIR,
        BAND_SWIR1: NIR,  # ndmi / bsi / msi read SWIR1
        BAND_SWIR2: NIR,
    }
    result = compute_all_indices(bands)
    # Tied to the constant rather than a literal list, so adding an index in
    # one place and forgetting the other fails here.
    assert set(result.keys()) == set(STANDARD_INDEX_CODES)
    assert {
        "ndvi",
        "ndwi",
        "evi",
        "savi",
        "ndre",
        "gndvi",
        "ndmi",
        "bsi",
        "msi",
        "msavi",
    } == set(result)
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
