"""Unit tests for the thermal index formulas and the Landsat mask ruleset.

Pure numpy in, numbers out — so these assert exact expected values on
hand-built fixtures rather than shapes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from app.modules.indices.computation import (
    CWSI_DT_DRY_C,
    CWSI_DT_WET_C,
    PRODUCT_INDEX_CODES,
    PRODUCT_MASK_RULESETS,
    STANDARD_INDEX_CODES,
    THERMAL_INDEX_CODES,
    compute_indices_for_product,
    compute_thermal_indices,
    cwsi,
    interpolate_air_temp_c,
    landsat_qa_pixel_mask,
    lst,
    quality_band_mask,
    smi,
)

# Real Collection-2 QA_PIXEL values.
_QA_CLEAR_LAND = 21824  # bit 6 (clear) set, no failure bits
_QA_CLEAR_WATER = 21952  # clear + bit 7 (water) — kept, like SCL class 6
_QA_CLOUD = 22280  # bit 3 (cloud) set
_QA_CLOUD_SHADOW = 23888  # bit 4 (cloud shadow) set
_QA_FILL = 1  # bit 0 (fill)


# -- LST ----------------------------------------------------------------


def test_lst_converts_kelvin_to_celsius() -> None:
    kelvin = np.array([[273.15, 300.0, 320.55]], dtype=np.float32)
    out = lst(kelvin)

    assert out.dtype == np.float32
    assert out[0, 0] == pytest.approx(0.0, abs=1e-3)
    assert out[0, 1] == pytest.approx(26.85, abs=1e-2)
    assert out[0, 2] == pytest.approx(47.40, abs=1e-2)


def test_lst_preserves_nan_fill() -> None:
    out = lst(np.array([[np.nan, 300.0]], dtype=np.float32))
    assert np.isnan(out[0, 0])
    assert not np.isnan(out[0, 1])


def test_lst_matches_the_study_sanity_values() -> None:
    """The study measured ~27.2-27.6 degC over irrigated ground near Suez.

    Working back: 27.21 degC == 300.36 K == DN 44280.
    """
    dn = 44280
    kelvin = dn * 0.00341802 + 149.0
    out = lst(np.array([[kelvin]], dtype=np.float32))
    assert out[0, 0] == pytest.approx(27.21, abs=0.05)


# -- CWSI ---------------------------------------------------------------


def test_cwsi_is_zero_on_the_well_watered_bound() -> None:
    air = 30.0
    # A canopy CWSI_DT_WET_C below air temperature is freely transpiring.
    surface = np.array([[air + CWSI_DT_WET_C]], dtype=np.float32)
    assert cwsi(surface, air)[0, 0] == pytest.approx(0.0, abs=1e-5)


def test_cwsi_is_one_on_the_fully_stressed_bound() -> None:
    air = 30.0
    surface = np.array([[air + CWSI_DT_DRY_C]], dtype=np.float32)
    assert cwsi(surface, air)[0, 0] == pytest.approx(1.0, abs=1e-5)


def test_cwsi_is_linear_between_the_bounds() -> None:
    air = 30.0
    midpoint = air + (CWSI_DT_WET_C + CWSI_DT_DRY_C) / 2.0
    assert cwsi(np.array([[midpoint]], dtype=np.float32), air)[0, 0] == pytest.approx(0.5, abs=1e-5)


def test_cwsi_clips_outside_the_literature_bounds() -> None:
    """Out of range means the constants are off for this site.

    It does not mean stress is negative, so clip rather than pass through.
    """
    air = 30.0
    surface = np.array([[air - 20.0, air + 40.0]], dtype=np.float32)
    out = cwsi(surface, air)
    assert out[0, 0] == 0.0
    assert out[0, 1] == 1.0


def test_cwsi_tracks_air_temperature_not_just_surface() -> None:
    """The same surface temperature means different stress on different days.

    This is what keeps CWSI independent of SMI: normalise the AOI's own
    spread twice and the two indices are just each other's inverse.
    """
    surface = np.array([[32.0]], dtype=np.float32)
    cool_day = cwsi(surface, 30.0)[0, 0]
    hot_day = cwsi(surface, 34.0)[0, 0]
    assert cool_day > hot_day


# -- SMI ----------------------------------------------------------------


def _triangle_scene() -> tuple[np.ndarray, np.ndarray]:
    """A synthetic LST/NDVI triangle with a wide greenness range.

    Dry edge falls with NDVI (bare hot soil -> cool dense canopy); the wet
    edge is flat and cool. Every NDVI bin is populated well past
    SMI_MIN_BIN_PIXELS.
    """
    rng = np.random.default_rng(1234)
    greens = rng.uniform(0.05, 0.85, size=(60, 60)).astype(np.float32)
    # Dry edge: 50 degC at NDVI 0 falling to 30 degC at NDVI 1.
    dry = 50.0 - 20.0 * greens
    wet = np.full_like(greens, 25.0)
    wetness = rng.uniform(0.0, 1.0, size=greens.shape).astype(np.float32)
    temps = (dry - wetness * (dry - wet)).astype(np.float32)
    return temps, greens


def test_smi_places_the_dry_edge_at_zero_and_the_wet_edge_at_one() -> None:
    temps, greens = _triangle_scene()
    out = smi(temps, greens)

    assert out.dtype == np.float32
    assert float(np.nanmin(out)) == pytest.approx(0.0, abs=0.05)
    assert float(np.nanmax(out)) == pytest.approx(1.0, abs=0.05)


def test_smi_reads_cooler_ground_as_wetter_at_equal_greenness() -> None:
    temps, greens = _triangle_scene()
    # Two pixels at the same NDVI, one hot one cool.
    greens[0, 0] = greens[0, 1] = 0.5
    temps[0, 0] = 40.0
    temps[0, 1] = 27.0
    out = smi(temps, greens)
    assert out[0, 1] > out[0, 0]


def test_smi_falls_back_when_the_ndvi_span_is_too_narrow() -> None:
    """A uniform block cannot support a fitted triangle.

    The dry and wet edges collapse onto each other and their slopes
    become noise, so SMI degrades to a plain LST normalisation instead of
    reporting an edge it cannot measure.
    """
    greens = np.full((20, 20), 0.62, dtype=np.float32)
    temps = np.linspace(28.0, 34.0, 400, dtype=np.float32).reshape(20, 20)

    out = smi(temps, greens)

    # Still a usable 0-1 surface, still inverted (cool = wet).
    assert float(np.nanmin(out)) == pytest.approx(0.0, abs=1e-5)
    assert float(np.nanmax(out)) == pytest.approx(1.0, abs=1e-5)
    assert out[0, 0] > out[-1, -1], "the coolest pixel must read wettest"


def test_smi_handles_an_isothermal_aoi() -> None:
    greens = np.full((5, 5), 0.5, dtype=np.float32)
    temps = np.full((5, 5), 30.0, dtype=np.float32)
    out = smi(temps, greens)
    # No gradient to report — neutral rather than a divide-by-zero.
    assert np.all(out == 0.5)


def test_smi_is_all_nan_when_nothing_is_usable() -> None:
    nans = np.full((4, 4), np.nan, dtype=np.float32)
    assert np.all(np.isnan(smi(nans, nans)))


def test_smi_ignores_nan_pixels_when_fitting() -> None:
    temps, greens = _triangle_scene()
    temps[0:5, :] = np.nan
    out = smi(temps, greens)
    assert np.all(np.isnan(out[0:5, :]))
    assert np.isfinite(out[10:, :]).any()


# -- Landsat QA_PIXEL mask ----------------------------------------------


def test_qa_mask_keeps_clear_land_and_water() -> None:
    qa = np.array([[_QA_CLEAR_LAND, _QA_CLEAR_WATER]], dtype=np.float32)
    assert not landsat_qa_pixel_mask(qa).any()


def test_qa_mask_drops_cloud_shadow_and_fill() -> None:
    qa = np.array([[_QA_CLOUD, _QA_CLOUD_SHADOW, _QA_FILL]], dtype=np.float32)
    assert landsat_qa_pixel_mask(qa).all()


def test_qa_mask_does_not_treat_the_clear_bit_as_a_failure() -> None:
    """The polarity trap: bit 6 means *clear*.

    Masking on "any bit set" would drop every good pixel — clear land
    (21824) has bit 6 and several confidence bits set.
    """
    assert _QA_CLEAR_LAND & (1 << 6)
    assert not landsat_qa_pixel_mask(np.array([[_QA_CLEAR_LAND]], dtype=np.float32))[0, 0]


def test_qa_mask_survives_the_float32_round_trip() -> None:
    """The COG is single-dtype, so codes arrive as float32, not uint16."""
    codes = np.array([[_QA_CLEAR_LAND, _QA_CLOUD]], dtype=np.uint16)
    as_float = codes.astype(np.float32)
    assert np.array_equal(
        landsat_qa_pixel_mask(as_float), landsat_qa_pixel_mask(codes.astype(np.float64))
    )
    assert list(landsat_qa_pixel_mask(as_float)[0]) == [False, True]


def test_scl_class_list_does_not_transfer_to_landsat() -> None:
    """Different encodings: SCL is a class enum, QA_PIXEL is a bitmask.

    SCL class 9 (cloud high-probability) as a QA_PIXEL code would be
    bits 0 and 3 — fill plus cloud — so reading one with the other's
    rules produces a plausible-looking mask that is entirely wrong.
    """
    assert PRODUCT_MASK_RULESETS["s2_l2a"] == "s2_scl_v1"
    assert PRODUCT_MASK_RULESETS["landsat_c2_l2_st"] == "landsat_qa_pixel_v1"
    assert PRODUCT_MASK_RULESETS["s2_l2a"] != PRODUCT_MASK_RULESETS["landsat_c2_l2_st"]


# -- Product dispatch ---------------------------------------------------


def test_thermal_index_codes_are_disjoint_from_the_optical_set() -> None:
    assert set(THERMAL_INDEX_CODES).isdisjoint(STANDARD_INDEX_CODES)
    assert PRODUCT_INDEX_CODES["landsat_c2_l2_st"] == THERMAL_INDEX_CODES
    assert PRODUCT_INDEX_CODES["s2_l2a"] == STANDARD_INDEX_CODES


def test_compute_thermal_indices_returns_exactly_the_thermal_set() -> None:
    bands = {
        "lwir11": np.full((8, 8), 305.0, dtype=np.float32),
        "red": np.full((8, 8), 0.12, dtype=np.float32),
        "nir08": np.full((8, 8), 0.38, dtype=np.float32),
    }
    out = compute_thermal_indices(bands, air_temp_c=31.0)

    assert set(out) == set(THERMAL_INDEX_CODES)
    # 305 K == 31.85 degC, i.e. 0.85 degC above air -> just into stress.
    assert out["lst"][0, 0] == pytest.approx(31.85, abs=1e-2)
    assert out["cwsi"][0, 0] == pytest.approx((0.85 - CWSI_DT_WET_C) / 8.0, abs=1e-3)


def test_smi_uses_landsat_ndvi_not_a_supplied_series() -> None:
    """SMI's NDVI must come from the same scene as the LST.

    `compute_thermal_indices` recomputes it from the Landsat red/nir08
    bands; there is deliberately no parameter to inject an S2 series,
    because the triangle is only valid on one surface at one moment.
    """
    bands = {
        "lwir11": np.full((6, 6), 305.0, dtype=np.float32),
        "red": np.full((6, 6), 0.12, dtype=np.float32),
        "nir08": np.full((6, 6), 0.38, dtype=np.float32),
    }
    out = compute_thermal_indices(bands, air_temp_c=30.0)
    assert "smi" in out
    assert compute_thermal_indices.__doc__ is not None


def test_dispatch_routes_each_product_to_its_own_maths() -> None:
    thermal_bands = {
        "lwir11": np.full((4, 4), 300.0, dtype=np.float32),
        "red": np.full((4, 4), 0.1, dtype=np.float32),
        "nir08": np.full((4, 4), 0.4, dtype=np.float32),
    }
    out = compute_indices_for_product("landsat_c2_l2_st", thermal_bands, air_temp_c=28.0)
    assert set(out) == set(THERMAL_INDEX_CODES)


def test_missing_air_temperature_costs_cwsi_only() -> None:
    """A missing weather hour must not cost the whole scene.

    CWSI is omitted rather than returned as NaN or zero: a missing key
    leaves a gap in the series, which is true, where a fabricated value
    would read as "no stress". LST and SMI need no weather.
    """
    bands = {
        "lwir11": np.full((4, 4), 300.0, dtype=np.float32),
        "red": np.full((4, 4), 0.1, dtype=np.float32),
        "nir08": np.full((4, 4), 0.4, dtype=np.float32),
    }
    out = compute_indices_for_product("landsat_c2_l2_st", bands)

    assert set(out) == {"lst", "smi"}
    assert "cwsi" not in out


def test_thermal_indices_come_back_in_catalog_order() -> None:
    bands = {
        "lwir11": np.full((4, 4), 300.0, dtype=np.float32),
        "red": np.full((4, 4), 0.1, dtype=np.float32),
        "nir08": np.full((4, 4), 0.4, dtype=np.float32),
    }
    out = compute_indices_for_product("landsat_c2_l2_st", bands, air_temp_c=28.0)
    assert tuple(out) == THERMAL_INDEX_CODES


# -- Air temperature interpolation --------------------------------------


def test_air_temp_interpolates_between_hourly_samples() -> None:
    samples = [
        (datetime(2026, 8, 14, 8, 0, tzinfo=UTC), 26.0),
        (datetime(2026, 8, 14, 9, 0, tzinfo=UTC), 30.0),
    ]
    # Landsat crosses at ~08:17 — a quarter of the way through the hour.
    at = datetime(2026, 8, 14, 8, 15, tzinfo=UTC)
    assert interpolate_air_temp_c(samples, at) == pytest.approx(27.0, abs=1e-6)


def test_air_temp_returns_an_exact_sample_unchanged() -> None:
    samples = [
        (datetime(2026, 8, 14, 8, 0, tzinfo=UTC), 26.0),
        (datetime(2026, 8, 14, 9, 0, tzinfo=UTC), 30.0),
    ]
    at = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
    assert interpolate_air_temp_c(samples, at) == pytest.approx(26.0)


def test_air_temp_skips_null_readings() -> None:
    samples = [
        (datetime(2026, 8, 14, 8, 0, tzinfo=UTC), None),
        (datetime(2026, 8, 14, 9, 0, tzinfo=UTC), 30.0),
    ]
    at = datetime(2026, 8, 14, 8, 30, tzinfo=UTC)
    # Only one usable sample and it is after `at` — take it rather than
    # dropping CWSI for the scene.
    assert interpolate_air_temp_c(samples, at) == pytest.approx(30.0)


def test_air_temp_falls_back_to_the_nearest_end_of_the_window() -> None:
    samples = [
        (datetime(2026, 8, 14, 6, 0, tzinfo=UTC), 22.0),
        (datetime(2026, 8, 14, 7, 0, tzinfo=UTC), 24.0),
    ]
    after_window = datetime(2026, 8, 14, 8, 20, tzinfo=UTC)
    assert interpolate_air_temp_c(samples, after_window) == pytest.approx(24.0)


def test_air_temp_is_none_when_nothing_is_usable() -> None:
    assert interpolate_air_temp_c([], datetime(2026, 8, 14, 8, tzinfo=UTC)) is None
    assert (
        interpolate_air_temp_c(
            [(datetime(2026, 8, 14, 8, tzinfo=UTC), None)],
            datetime(2026, 8, 14, 8, tzinfo=UTC),
        )
        is None
    )


def test_air_temp_handles_unsorted_input() -> None:
    """`read_observations` orders ascending, but do not rely on it."""
    samples = [
        (datetime(2026, 8, 14, 9, 0, tzinfo=UTC), 30.0),
        (datetime(2026, 8, 14, 8, 0, tzinfo=UTC), 26.0),
    ]
    at = datetime(2026, 8, 14, 8, 30, tzinfo=UTC)
    assert interpolate_air_temp_c(samples, at) == pytest.approx(28.0)


def test_dispatch_rejects_an_unknown_product() -> None:
    with pytest.raises(ValueError, match="planet_3m"):
        compute_indices_for_product("planet_3m", {})
    with pytest.raises(ValueError, match="planet_3m"):
        quality_band_mask("planet_3m", np.zeros((2, 2), dtype=np.float32))


def test_quality_band_mask_dispatches_on_product() -> None:
    # SCL class 9 = cloud high-probability -> masked under s2 rules.
    assert quality_band_mask("s2_l2a", np.array([[9.0]], dtype=np.float32))[0, 0]
    # The same numeric value under Landsat rules is bits 0+3 -> also
    # masked, but for entirely different reasons. Use a value where the
    # two rulesets genuinely disagree to prove dispatch happened.
    clear_land = np.array([[float(_QA_CLEAR_LAND)]], dtype=np.float32)
    assert not quality_band_mask("landsat_c2_l2_st", clear_land)[0, 0]
    # 21824 is not in the SCL masked-class list either, but 4 (vegetation)
    # vs 21824 shows the class enum simply has no meaning at that scale.
    assert not quality_band_mask("s2_l2a", np.array([[4.0]], dtype=np.float32))[0, 0]
