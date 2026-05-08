"""Pure-function unit tests for `weather/derivations.py`.

No DB or container needed — flagged ``integration`` only because the
shared conftest at ``tests/integration/conftest.py`` is the lightest
place to drop these alongside the rest of the weather suite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.modules.weather.derivations import (
    DailyDerived,
    HourlyRow,
    aggregate_one_day,
    bucket_hourly_by_local_date,
    cumulative_gdd_base10_for_season,
    rolling_precip_total,
)

pytestmark = [pytest.mark.integration]


def _hourly(
    iso: str,
    temp: float | None = None,
    precip: float | None = None,
    et0: float | None = None,
) -> HourlyRow:
    return HourlyRow(
        time=datetime.fromisoformat(iso).replace(tzinfo=UTC),
        air_temp_c=Decimal(str(temp)) if temp is not None else None,
        precipitation_mm=Decimal(str(precip)) if precip is not None else None,
        et0_mm=Decimal(str(et0)) if et0 is not None else None,
    )


# --- bucket_hourly_by_local_date -------------------------------------------


def test_bucket_respects_local_tz() -> None:
    """A UTC hour falling after midnight Cairo lands on the next local date.

    Africa/Cairo is UTC+3 (DST EEST) in May 2026, so 21:00 UTC equals
    00:00 the next day local time. The bucketing must put hours on
    either side of that boundary on different local dates even though
    they're consecutive in UTC.
    """
    cairo = ZoneInfo("Africa/Cairo")
    rows = (
        _hourly("2026-05-06T20:00:00", temp=20),  # 23:00 Cairo, May 6
        _hourly("2026-05-06T21:00:00", temp=18),  # 00:00 Cairo, May 7
        _hourly("2026-05-06T22:00:00", temp=16),  # 01:00 Cairo, May 7
    )
    buckets = bucket_hourly_by_local_date(rows, cairo)
    assert set(buckets.keys()) == {date(2026, 5, 6), date(2026, 5, 7)}
    assert len(buckets[date(2026, 5, 6)]) == 1
    assert len(buckets[date(2026, 5, 7)]) == 2


# --- aggregate_one_day ------------------------------------------------------


def test_aggregate_one_day_basic() -> None:
    rows = (
        _hourly("2026-05-06T00:00:00", temp=15.0, precip=0.0, et0=0.0),
        _hourly("2026-05-06T12:00:00", temp=25.0, precip=2.5, et0=0.4),
        _hourly("2026-05-06T18:00:00", temp=20.0, precip=0.5, et0=0.1),
    )
    out = aggregate_one_day(rows, date(2026, 5, 6))
    assert out.temp_min_c == Decimal("15.0")
    assert out.temp_max_c == Decimal("25.0")
    assert out.temp_mean_c == Decimal("20.00")
    assert out.precip_mm_daily == Decimal("3.00")
    assert out.et0_mm_daily == Decimal("0.50")
    # GDD base 10: max(0, 20 - 10) = 10. Base 15: max(0, 20 - 15) = 5.
    assert out.gdd_base10 == Decimal("10.00")
    assert out.gdd_base15 == Decimal("5.00")


def test_aggregate_one_day_cold_day_clamps_gdd_at_zero() -> None:
    """A day whose mean falls below the base temp produces GDD = 0."""
    rows = (
        _hourly("2026-01-01T00:00:00", temp=5.0),
        _hourly("2026-01-01T12:00:00", temp=8.0),
    )
    out = aggregate_one_day(rows, date(2026, 1, 1))
    assert out.gdd_base10 == Decimal("0")
    assert out.gdd_base15 == Decimal("0")


def test_aggregate_one_day_handles_all_null_inputs() -> None:
    rows = (_hourly("2026-05-06T00:00:00"),)
    out = aggregate_one_day(rows, date(2026, 5, 6))
    assert out.temp_min_c is None
    assert out.temp_max_c is None
    assert out.temp_mean_c is None
    assert out.precip_mm_daily is None
    assert out.et0_mm_daily is None
    assert out.gdd_base10 is None


def test_aggregate_one_day_partial_nulls_use_present_values_only() -> None:
    """A column with one missing value still aggregates from what's there."""
    rows = (
        _hourly("2026-05-06T00:00:00", temp=15.0, precip=None),
        _hourly("2026-05-06T12:00:00", temp=25.0, precip=2.0),
    )
    out = aggregate_one_day(rows, date(2026, 5, 6))
    assert out.temp_mean_c == Decimal("20.00")
    assert out.precip_mm_daily == Decimal("2.00")  # only the non-null hour


# --- cumulative_gdd_base10_for_season --------------------------------------


def _daily(d: date, gdd: float | None = None, precip: float | None = None) -> DailyDerived:
    return DailyDerived(
        date=d,
        temp_min_c=None,
        temp_max_c=None,
        temp_mean_c=None,
        precip_mm_daily=Decimal(str(precip)) if precip is not None else None,
        et0_mm_daily=None,
        gdd_base10=Decimal(str(gdd)) if gdd is not None else None,
        gdd_base15=None,
    )


def test_cumulative_gdd_sums_from_jan_first() -> None:
    by_day = {
        date(2026, 1, 1): _daily(date(2026, 1, 1), gdd=5),
        date(2026, 1, 2): _daily(date(2026, 1, 2), gdd=3),
        date(2026, 5, 6): _daily(date(2026, 5, 6), gdd=10),
    }
    # Cumulative through 2026-05-06 should sum every day with non-null GDD
    # in the season window (Jan 1 .. May 6 inclusive). Missing days don't
    # contribute.
    cum = cumulative_gdd_base10_for_season(by_day, date(2026, 5, 6))
    assert cum == Decimal("18.00")


def test_cumulative_gdd_returns_none_when_season_is_empty() -> None:
    cum = cumulative_gdd_base10_for_season({}, date(2026, 5, 6))
    assert cum is None


def test_cumulative_gdd_resets_at_year_boundary() -> None:
    """A 2025 row must not bleed into 2026's season cumulative."""
    by_day = {
        date(2025, 12, 31): _daily(date(2025, 12, 31), gdd=999),
        date(2026, 1, 1): _daily(date(2026, 1, 1), gdd=5),
    }
    cum = cumulative_gdd_base10_for_season(by_day, date(2026, 1, 1))
    assert cum == Decimal("5.00")


# --- rolling_precip_total --------------------------------------------------


def test_rolling_precip_window_inclusive() -> None:
    """7-day window includes the target date and the prior 6 days."""
    by_day = {
        date(2026, 5, 6)
        - timedelta(days=offset): _daily(date(2026, 5, 6) - timedelta(days=offset), precip=1.0)
        for offset in range(10)
    }
    total = rolling_precip_total(by_day, date(2026, 5, 6), window_days=7)
    assert total == Decimal("7.00")


def test_rolling_precip_returns_none_when_all_window_days_missing() -> None:
    by_day = {date(2026, 1, 1): _daily(date(2026, 1, 1), precip=10)}
    total = rolling_precip_total(by_day, date(2026, 5, 6), window_days=7)
    assert total is None


def test_rolling_precip_zero_observed_is_data_not_missing() -> None:
    by_day = {
        date(2026, 5, 6): _daily(date(2026, 5, 6), precip=0.0),
    }
    total = rolling_precip_total(by_day, date(2026, 5, 6), window_days=7)
    assert total == Decimal("0.00")


def test_rolling_precip_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="window_days"):
        rolling_precip_total({}, date(2026, 5, 6), window_days=0)
