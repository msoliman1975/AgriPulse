"""Unit tests for interpolating the hourly weather feed to a moment.

Lives with `weather` rather than `indices`: interpolating an hourly feed
is weather maths, and `imagery` reaches it through `WeatherService`
because the import contract makes `weather.repository` private.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.weather.interpolation import interpolate_air_temp_c


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
