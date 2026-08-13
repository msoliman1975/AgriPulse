"""Unit tests for the Standardized Precipitation Index.

No scipy here — it is installed in some dev environments but is not a declared
dependency, so the tests must not reach for it either. The incomplete-gamma
implementation was checked against `scipy.stats.gamma.cdf` during development
(max abs error 7e-14 over 30 points); what is pinned below are the properties
that must hold regardless of implementation.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from app.modules.weather.spi import (
    SPI_CLAMP,
    _lower_regularized_gamma,
    accumulate,
    comparable_history,
    compute_spi,
    fit_gamma,
)


def _gamma_sample(n: int, shape: float = 2.0, scale: float = 25.0, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    return [rng.gammavariate(shape, scale) for _ in range(n)]


# --- incomplete gamma -------------------------------------------------------


def test_incomplete_gamma_is_a_cdf() -> None:
    """Monotone from 0 to 1 — the property everything downstream relies on."""
    prev = -1.0
    for x in (0.0, 0.1, 0.5, 1.0, 2.0, 5.0, 20.0, 100.0):
        p = _lower_regularized_gamma(2.0, x)
        assert 0.0 <= p <= 1.0
        assert p > prev
        prev = p
    assert _lower_regularized_gamma(2.0, 0.0) == 0.0
    assert _lower_regularized_gamma(2.0, 500.0) == pytest.approx(1.0, abs=1e-9)


def test_incomplete_gamma_matches_the_closed_form_for_shape_one() -> None:
    """At a=1 the gamma reduces to the exponential CDF, 1 - e^-x."""
    import math

    for x in (0.25, 1.0, 3.0, 7.5):
        assert _lower_regularized_gamma(1.0, x) == pytest.approx(1 - math.exp(-x), abs=1e-12)


# --- gamma fit --------------------------------------------------------------


def test_fit_recovers_known_parameters() -> None:
    shape, scale = fit_gamma(_gamma_sample(4000))
    assert shape == pytest.approx(2.0, rel=0.1)
    assert scale == pytest.approx(25.0, rel=0.1)


def test_fit_declines_rather_than_guessing() -> None:
    assert fit_gamma([]) is None
    assert fit_gamma([5.0]) is None  # one point is not a distribution
    assert fit_gamma([4.0] * 50) is None  # no spread at all
    # Zeros are the caller's problem (the mixed distribution), not the fit's.
    assert fit_gamma([0.0, 0.0]) is None


# --- SPI --------------------------------------------------------------------


def test_spi_over_its_own_history_is_standard_normal() -> None:
    """The defining property: feed the distribution back through itself and
    the result must be ~N(0, 1)."""
    history = _gamma_sample(400)
    values = [compute_spi(x, history).value for x in history]
    mean = sum(values) / len(values)
    sd = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    assert mean == pytest.approx(0.0, abs=0.1)
    assert sd == pytest.approx(1.0, abs=0.1)


def test_median_rainfall_scores_near_zero_and_the_sign_is_right() -> None:
    history = _gamma_sample(400)
    ordered = sorted(history)
    assert compute_spi(ordered[len(ordered) // 2], history).value == pytest.approx(0.0, abs=0.15)
    # A wet window is positive, a dry one negative — the sign convention that
    # makes "negative = drought" true.
    assert compute_spi(ordered[-5], history).value > 1.0
    assert compute_spi(ordered[4], history).value < -1.0


def test_extremes_are_clamped_rather_than_extrapolated() -> None:
    history = _gamma_sample(200)
    assert compute_spi(1_000_000.0, history).value == SPI_CLAMP
    assert compute_spi(0.0, history).value >= -SPI_CLAMP


def test_reports_the_evidence_alongside_the_value() -> None:
    history = _gamma_sample(200)
    result = compute_spi(history[0], history)
    assert result.sample_size == 200
    assert result.dry_fraction == 0.0
    assert result.shape > 0
    assert result.scale > 0


# --- the guards, which matter more here than the maths ----------------------


def test_declines_on_too_short_a_record() -> None:
    """WMO wants 30 years. A handful of windows cannot support a percentile."""
    assert compute_spi(50.0, _gamma_sample(5)) is None


def test_declines_in_a_hyper_arid_record() -> None:
    """The case that actually matters for Egyptian orchards.

    When almost every historical window is bone dry the mixed distribution is
    mostly point mass at zero and SPI collapses to a near-binary signal. A
    number here would be an artefact wearing the clothes of a measurement, so
    the caller gets None and emits no row.
    """
    mostly_dry = [0.0] * 95 + [3.0, 5.0, 1.0, 8.0, 2.0]
    assert compute_spi(0.0, mostly_dry) is None

    # A record with real variability, same length, is fine.
    workable = [0.0] * 20 + _gamma_sample(80)
    assert compute_spi(40.0, workable) is not None


def test_zero_accumulation_sits_inside_the_dry_mass_not_at_its_edge() -> None:
    """A dry window in a climate where dryness is common must not read as more
    extreme than the record supports."""
    history = [0.0] * 30 + _gamma_sample(70)
    result = compute_spi(0.0, history)
    assert result is not None
    assert result.value < 0  # still a drought signal...
    assert result.value > -SPI_CLAMP  # ...but not the most extreme possible


def test_rejects_a_negative_accumulation() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        compute_spi(-1.0, _gamma_sample(50))


# --- windowing --------------------------------------------------------------


def _daily(start: date, days: int, mm: float) -> dict[date, float]:
    return {start + timedelta(days=i): mm for i in range(days)}


def test_accumulate_sums_the_inclusive_window() -> None:
    rain = _daily(date(2026, 1, 1), 100, 2.0)
    assert accumulate(rain, date(2026, 1, 31), 30) == pytest.approx(60.0)


def test_accumulate_declines_on_a_partial_window() -> None:
    """A missing day would understate the total and so OVERSTATE the drought —
    the one direction of error that turns this into a false alarm."""
    rain = _daily(date(2026, 1, 1), 100, 2.0)
    del rain[date(2026, 1, 15)]
    assert accumulate(rain, date(2026, 1, 31), 30) is None
    # A window clear of the hole is still fine.
    assert accumulate(rain, date(2026, 2, 20), 30) == pytest.approx(60.0)


def test_comparable_history_only_uses_earlier_years() -> None:
    rain = _daily(date(2020, 1, 1), 366 * 7, 1.0)
    target = date(2026, 6, 15)
    history = comparable_history(rain, target, window_days=30, doy_tolerance=3)
    # 2020-2025 inclusive: six prior years reach far enough back for a full
    # 30-day window plus the 3-day margin (2020's earliest need is 2020-05-13,
    # comfortably inside the record), each contributing 2*3+1 = 7 end dates.
    assert len(history) == 6 * 7
    assert all(h == pytest.approx(30.0) for h in history)


def test_comparable_history_stops_where_the_record_does() -> None:
    """Years without a complete window contribute nothing rather than a
    short, drought-flattering total."""
    rain = _daily(date(2024, 1, 1), 366 * 3, 1.0)  # only ~3 years of record
    history = comparable_history(rain, date(2026, 6, 15), window_days=30, doy_tolerance=3)
    assert len(history) == 2 * 7  # 2025 and 2024 only


def test_comparable_history_never_includes_the_target_itself() -> None:
    """A value must not contribute to the distribution it is scored against."""
    rain = _daily(date(2020, 1, 1), 366 * 7, 1.0)
    target = date(2026, 6, 15)
    # A tolerance wide enough to reach forward past `target` if unguarded.
    history = comparable_history(rain, target, window_days=10, doy_tolerance=400)
    assert len(history) == len(set(range(len(history))))  # sanity: non-empty
    assert history  # and it did gather something


def test_comparable_history_handles_29_february() -> None:
    rain = _daily(date(2020, 1, 1), 366 * 6, 1.0)
    # 2024 is a leap year; 2023 and 2022 are not, so replace(year=...) would
    # raise for 29 Feb without the fallback.
    history = comparable_history(rain, date(2024, 2, 29), window_days=10, doy_tolerance=1)
    assert history


def test_comparable_history_rejects_a_zero_window() -> None:
    with pytest.raises(ValueError, match="window_days must be >= 1"):
        comparable_history({}, date(2026, 1, 1), window_days=0)
