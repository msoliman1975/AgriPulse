"""Pure-function tests for the risk-window bridge (PR-R2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.weather.derivations import DailyDerived
from app.modules.weather.index_projection import RadiationWindDay
from app.modules.weather.risk_projection import build_risk_window


def _d(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _daily(tmean: float | None, precip: float | None) -> DailyDerived:
    # build_risk_window keys off the map, not DailyDerived.date, so the date
    # here is an unused-but-required placeholder.
    return DailyDerived(
        date=date(2026, 1, 1),
        temp_min_c=_d(tmean),
        temp_max_c=_d(tmean),
        temp_mean_c=_d(tmean),
        precip_mm_daily=_d(precip),
        et0_mm_daily=None,
        gdd_base10=None,
        gdd_base15=None,
    )


def _rw(humidity: float | None) -> RadiationWindDay:
    return RadiationWindDay(
        radiation_mean_w_m2=None,
        radiation_sum_mj_m2=None,
        wind_mean_m_s=None,
        wind_max_m_s=None,
        wind_dir_mean_deg=None,
        humidity_mean_pct=_d(humidity),
    )


_AS_OF = date(2026, 6, 14)


def test_full_window_is_ascending_and_mapped() -> None:
    daily = {date(2026, 6, 12 + i): _daily(20 + i, i) for i in range(3)}
    radwind = {date(2026, 6, 12 + i): _rw(70 + i) for i in range(3)}
    window = build_risk_window(daily, radwind, as_of=_AS_OF, window_days=3)
    assert [d.date for d in window] == [date(2026, 6, 12), date(2026, 6, 13), date(2026, 6, 14)]
    last = window[-1]
    assert last.temp_mean_c == Decimal("22")
    assert last.humidity_mean_pct == Decimal("72")
    assert last.precip_mm == Decimal("2")


def test_gap_day_present_in_neither_map_is_omitted() -> None:
    daily = {date(2026, 6, 12): _daily(20, 0), date(2026, 6, 14): _daily(22, 0)}
    radwind = {date(2026, 6, 12): _rw(70), date(2026, 6, 14): _rw(72)}
    window = build_risk_window(daily, radwind, as_of=_AS_OF, window_days=3)
    # 2026-06-13 is in neither map -> dropped.
    assert [d.date for d in window] == [date(2026, 6, 12), date(2026, 6, 14)]


def test_radiation_only_day_keeps_humidity_with_null_temp() -> None:
    daily: dict[date, DailyDerived] = {}
    radwind = {_AS_OF: _rw(85)}
    window = build_risk_window(daily, radwind, as_of=_AS_OF, window_days=3)
    assert len(window) == 1
    assert window[0].humidity_mean_pct == Decimal("85")
    assert window[0].temp_mean_c is None
    assert window[0].precip_mm is None


def test_daily_only_day_has_null_humidity() -> None:
    window = build_risk_window({_AS_OF: _daily(23, 1)}, {}, as_of=_AS_OF, window_days=3)
    assert len(window) == 1
    assert window[0].temp_mean_c == Decimal("23")
    assert window[0].humidity_mean_pct is None


def test_window_excludes_days_outside_the_span() -> None:
    # 5 days of data but a 2-day window keeps only as_of and the day before.
    daily = {date(2026, 6, 10 + i): _daily(20, 0) for i in range(5)}
    window = build_risk_window(daily, {}, as_of=_AS_OF, window_days=2)
    assert [d.date for d in window] == [date(2026, 6, 13), date(2026, 6, 14)]


def test_window_days_must_be_positive() -> None:
    with pytest.raises(ValueError, match="window_days"):
        build_risk_window({}, {}, as_of=_AS_OF, window_days=0)
