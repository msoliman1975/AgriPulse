"""Unit tests for the pure index-trend computation (KB P2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.modules.indices.trends import (
    FALLING,
    RISING,
    STABLE,
    compute_trend,
)

_T0 = datetime(2026, 6, 1, tzinfo=UTC)


def _pt(day: int, value: float | None) -> tuple[datetime, float | None]:
    return (_T0 + timedelta(days=day), value)


def test_rising_series() -> None:
    r = compute_trend([_pt(0, 0.40), _pt(5, 0.50), _pt(10, 0.62)])
    assert r.direction == RISING
    assert r.delta == Decimal("0.2200")  # 0.62 - 0.40
    assert r.slope is not None
    assert r.slope > 0


def test_falling_series() -> None:
    r = compute_trend([_pt(0, 0.70), _pt(6, 0.55), _pt(12, 0.40)])
    assert r.direction == FALLING
    assert r.delta == Decimal("-0.3000")
    assert r.slope is not None
    assert r.slope < 0


def test_flat_within_eps_is_stable() -> None:
    # total change 0.01 < default eps 0.02 → stable
    r = compute_trend([_pt(0, 0.50), _pt(7, 0.505), _pt(14, 0.51)])
    assert r.direction == STABLE


def test_too_few_points_returns_none() -> None:
    r = compute_trend([_pt(0, 0.5)])
    assert r.slope is None
    assert r.delta is None
    assert r.direction is None


def test_unordered_input_is_sorted() -> None:
    # Same data as falling, shuffled — direction must still be FALLING.
    r = compute_trend([_pt(12, 0.40), _pt(0, 0.70), _pt(6, 0.55)])
    assert r.direction == FALLING
    assert r.delta == Decimal("-0.3000")


def test_none_values_are_filtered() -> None:
    # Cloud-masked scenes (None) drop out; the remaining two rise.
    r = compute_trend([_pt(0, 0.40), _pt(5, None), _pt(10, 0.60)])
    assert r.direction == RISING
    assert r.delta == Decimal("0.2000")


def test_filtering_below_min_points_returns_none() -> None:
    r = compute_trend([_pt(0, None), _pt(5, 0.5), _pt(10, None)])
    assert r.direction is None


def test_same_day_points_have_no_slope_but_keep_delta() -> None:
    # Zero variance in x → slope undefined; delta still reflects change.
    r = compute_trend([_pt(3, 0.40), _pt(3, 0.60)])
    assert r.slope is None
    assert r.delta == Decimal("0.2000")
    assert r.direction == RISING


def test_decimal_string_values_accepted() -> None:
    # Means arrive as Decimal from the DB layer.
    r = compute_trend([_pt(0, Decimal("0.40")), _pt(10, Decimal("0.30"))])
    assert r.direction == FALLING
    assert r.delta == Decimal("-0.1000")
