"""Pure-function unit tests for `weather/index_projection.py`.

No DB/container — flagged ``integration`` only so the shared weather
conftest applies (same convention as ``test_derivations.py``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.modules.weather.derivations import DailyDerived
from app.modules.weather.index_projection import (
    IndexHourlyRow,
    aggregate_radiation_wind_day,
    bucket_index_hourly_by_local_date,
    dry_down_total,
    project_indices,
)

pytestmark = [pytest.mark.integration]


def _day(
    on: date,
    *,
    tmin: float | None = None,
    tmax: float | None = None,
    tmean: float | None = None,
    precip: float | None = None,
    et0: float | None = None,
) -> DailyDerived:
    def _dec(v: float | None) -> Decimal | None:
        return Decimal(str(v)) if v is not None else None

    return DailyDerived(
        date=on,
        temp_min_c=_dec(tmin),
        temp_max_c=_dec(tmax),
        temp_mean_c=_dec(tmean),
        precip_mm_daily=_dec(precip),
        et0_mm_daily=_dec(et0),
        gdd_base10=None,
        gdd_base15=None,
    )


def _ih(iso_utc: str, **kw: float) -> IndexHourlyRow:
    return IndexHourlyRow(
        time=datetime.fromisoformat(iso_utc).replace(tzinfo=UTC),
        **{k: Decimal(str(v)) for k, v in kw.items()},
    )


# --- aggregate_radiation_wind_day ------------------------------------------


def test_aggregate_radiation_wind_day_basic() -> None:
    rows = [
        _ih(
            "2026-06-15T09:00",
            solar_radiation_w_m2=200,
            wind_speed_m_s=2,
            wind_direction_deg=0,
            humidity_pct=50,
        ),
        _ih(
            "2026-06-15T10:00",
            solar_radiation_w_m2=400,
            wind_speed_m_s=4,
            wind_direction_deg=90,
            humidity_pct=60,
        ),
    ]
    agg = aggregate_radiation_wind_day(rows)
    assert agg.radiation_mean_w_m2 == Decimal("300")
    # Insolation: (200+400) W/m2 * 3600 s / 1e6 = 2.16 MJ/m2.
    assert agg.radiation_sum_mj_m2 == Decimal("2.16")
    assert agg.wind_mean_m_s == Decimal("3")
    assert agg.wind_max_m_s == Decimal("4")
    # Vector mean of bearings 0° and 90° is 45°.
    assert agg.wind_dir_mean_deg == Decimal("45.0")
    assert agg.humidity_mean_pct == Decimal("55")


def test_aggregate_radiation_wind_day_empty_is_all_none() -> None:
    agg = aggregate_radiation_wind_day([])
    assert agg.radiation_mean_w_m2 is None
    assert agg.wind_mean_m_s is None
    assert agg.wind_dir_mean_deg is None


def test_vector_mean_direction_opposing_cancels_to_none() -> None:
    # 0° and 180° cancel — the mean bearing is undefined.
    rows = [
        _ih("2026-06-15T09:00", wind_speed_m_s=2, wind_direction_deg=0),
        _ih("2026-06-15T10:00", wind_speed_m_s=2, wind_direction_deg=180),
    ]
    agg = aggregate_radiation_wind_day(rows)
    assert agg.wind_dir_mean_deg is None
    assert agg.wind_mean_m_s == Decimal("2")


def test_bucket_index_hourly_by_local_date_splits_on_tz() -> None:
    # Fixed UTC+2 (no DST) so the split is deterministic year-round.
    tz = ZoneInfo("Etc/GMT-2")
    rows = [
        _ih("2026-06-15T21:00", wind_speed_m_s=1),  # 23:00 local -> 06-15
        _ih("2026-06-15T22:30", wind_speed_m_s=1),  # 00:30 local -> 06-16
    ]
    buckets = bucket_index_hourly_by_local_date(rows, tz)
    assert set(buckets) == {date(2026, 6, 15), date(2026, 6, 16)}


# --- dry_down_total --------------------------------------------------------


def test_dry_down_total_sums_et0_minus_precip_over_window() -> None:
    on = date(2026, 6, 15)
    daily = {
        on: _day(on, et0=5, precip=2),
        on - timedelta(days=1): _day(on - timedelta(days=1), et0=4, precip=10),
    }
    # (5-2) + (4-10) = 3 - 6 = -3 → net surplus.
    assert dry_down_total(daily, on, window_days=30) == Decimal("-3")


def test_dry_down_total_none_without_et0() -> None:
    on = date(2026, 6, 15)
    daily = {on: _day(on, precip=2)}  # no et0
    assert dry_down_total(daily, on, window_days=30) is None


def test_dry_down_missing_precip_counts_as_zero_rain() -> None:
    on = date(2026, 6, 15)
    daily = {on: _day(on, et0=5)}  # precip None
    assert dry_down_total(daily, on, window_days=30) == Decimal("5")


# --- project_indices -------------------------------------------------------


def test_project_indices_full_day_emits_every_defined_index() -> None:
    on = date(2026, 6, 15)
    daily = {
        on: _day(on, tmin=18, tmax=30, tmean=24, precip=2, et0=5),
        on - timedelta(days=1): _day(on - timedelta(days=1), precip=10, et0=4),
    }
    radwind = aggregate_radiation_wind_day(
        [
            _ih(
                "2026-06-15T09:00",
                solar_radiation_w_m2=200,
                wind_speed_m_s=2,
                wind_direction_deg=180,
                humidity_pct=50,
            ),
            _ih(
                "2026-06-15T10:00",
                solar_radiation_w_m2=400,
                wind_speed_m_s=4,
                wind_direction_deg=180,
                humidity_pct=70,
            ),
        ]
    )
    by_code = {p.index_code: p for p in project_indices(on, daily, radwind)}

    assert set(by_code) == {
        "temperature",
        "radiation",
        "wind",
        "humidity",
        "rainfall",
        "evapotranspiration",
        "evaporation_coeff",
        "rain_et_balance",
        # 0062 gap-audit trio. This day carries a minimum, a maximum and
        # humidity, so all three are defined.
        "leaf_wetness",
        "frost_risk",
        "heat_stress",
    }
    # Daily MEAN relative humidity — (50 + 70) / 2.
    assert by_code["humidity"].value == Decimal("60")
    # Neither hour reached 90% RH, so a measured zero rather than no row.
    assert by_code["leaf_wetness"].value == Decimal("0")
    # A minimum of 18°C is nowhere near the 4°C watch threshold.
    assert by_code["frost_risk"].value == Decimal("0")
    assert by_code["temperature"].value == Decimal("24")
    assert by_code["temperature"].value_min == Decimal("18")
    assert by_code["temperature"].value_max == Decimal("30")
    assert by_code["radiation"].value == Decimal("300")
    assert by_code["wind"].value == Decimal("3")
    assert by_code["wind"].value_max == Decimal("4")
    assert by_code["wind"].value_aux["mean_direction_deg"] == "180.0"
    assert by_code["rainfall"].value == Decimal("2")
    # Rolling totals from the 2 present days = 2 + 10 = 12.
    assert by_code["rainfall"].value_aux["precip_mm_7d"] == "12.00"
    assert by_code["evapotranspiration"].value == Decimal("5")
    # Dry-down STOCK = (5-2)+(4-10) = -3; balance FLUX = 2-5 = -3.
    # Same number here, but they are distinct indices with distinct meaning.
    assert by_code["evaporation_coeff"].value == Decimal("-3")
    assert by_code["rain_et_balance"].value == Decimal("-3")


def test_project_indices_skips_undefined() -> None:
    on = date(2026, 6, 15)
    # Only a mean temperature; no precip/et0, no radiation/wind.
    daily = {on: _day(on, tmean=20)}
    codes = {p.index_code for p in project_indices(on, daily, None)}
    assert codes == {"temperature"}


def test_project_indices_emits_humidity_without_radiation_or_wind() -> None:
    """Humidity is independent of the radiation/wind columns it rides with —
    an hour with RH but no radiation still yields a humidity index row."""
    on = date(2026, 6, 15)
    daily = {on: _day(on, tmean=20)}
    radwind = aggregate_radiation_wind_day([_ih("2026-06-15T22:00", humidity_pct=88)])
    by_code = {p.index_code: p for p in project_indices(on, daily, radwind)}
    # leaf_wetness rides the same humidity column, so it appears here too —
    # at zero hours, because 88% is below the 90% wetness threshold.
    assert set(by_code) == {"temperature", "humidity", "leaf_wetness"}
    assert by_code["humidity"].value == Decimal("88")
    assert by_code["leaf_wetness"].value == Decimal("0")


# --- leaf wetness ----------------------------------------------------------


def test_leaf_wetness_counts_only_hours_at_or_above_the_threshold() -> None:
    on = date(2026, 6, 15)
    rows = [
        _ih("2026-06-15T00:00", humidity_pct=95),  # wet
        _ih("2026-06-15T01:00", humidity_pct=90),  # wet — boundary is inclusive
        _ih("2026-06-15T02:00", humidity_pct=89.9),  # dry, just
        _ih("2026-06-15T03:00", humidity_pct=40),  # dry
    ]
    radwind = aggregate_radiation_wind_day(rows)
    assert radwind.leaf_wetness_hours == Decimal(2)
    by_code = {p.index_code: p for p in project_indices(on, {on: _day(on, tmean=20)}, radwind)}
    assert by_code["leaf_wetness"].value == Decimal("2")
    assert by_code["leaf_wetness"].value_aux["rh_threshold_pct"] == "90"
    assert by_code["leaf_wetness"].value_aux["sample_hours"] == "4"


def test_leaf_wetness_distinguishes_a_dry_day_from_an_unmeasured_one() -> None:
    """0 hours is a finding; None is a gap. A disease model must not confuse
    the two — treating "we didn't measure" as "it was dry" invents evidence
    of safety."""
    on = date(2026, 6, 15)
    dry = aggregate_radiation_wind_day([_ih("2026-06-15T00:00", humidity_pct=30)])
    assert dry.leaf_wetness_hours == Decimal(0)

    unmeasured = aggregate_radiation_wind_day([_ih("2026-06-15T00:00", wind_speed_m_s=3)])
    assert unmeasured.leaf_wetness_hours is None
    # ...and an unmeasured day emits no row at all rather than a zero.
    codes = {p.index_code for p in project_indices(on, {on: _day(on, tmean=20)}, unmeasured)}
    assert "leaf_wetness" not in codes


# --- frost risk ------------------------------------------------------------


@pytest.mark.parametrize(
    ("tmin", "expected"),
    [
        (-3.0, Decimal(100)),  # hard frost
        (0.0, Decimal(100)),  # freezing — certain
        (1.0, Decimal(75)),
        (2.0, Decimal(50)),
        (4.0, Decimal(0)),  # watch threshold — no score
        (18.0, Decimal(0)),  # a warm night
    ],
)
def test_frost_risk_scales_from_the_daily_minimum(tmin: float, expected: Decimal) -> None:
    on = date(2026, 1, 10)
    daily = {on: _day(on, tmin=tmin, tmean=tmin + 5)}
    by_code = {p.index_code: p for p in project_indices(on, daily, None)}
    assert by_code["frost_risk"].value == expected
    assert by_code["frost_risk"].value_aux["temp_min_c"] == str(Decimal(str(tmin)))


def test_frost_risk_needs_a_minimum_not_just_a_mean() -> None:
    """A mean temperature says nothing about how cold the night got, which is
    the entire question."""
    on = date(2026, 1, 10)
    codes = {p.index_code for p in project_indices(on, {on: _day(on, tmean=8)}, None)}
    assert "frost_risk" not in codes


# --- heat stress -----------------------------------------------------------


def test_heat_stress_matches_the_thom_thi_formula() -> None:
    on = date(2026, 7, 20)
    daily = {on: _day(on, tmax=40, tmean=32)}
    radwind = aggregate_radiation_wind_day([_ih("2026-07-20T12:00", humidity_pct=30)])
    by_code = {p.index_code: p for p in project_indices(on, daily, radwind)}
    # THI = (1.8*40 + 32) - (0.55 - 0.0055*30) * (1.8*40 - 26)
    #     = 104 - (0.385 * 46) = 104 - 17.71 = 86.29
    assert by_code["heat_stress"].value == Decimal("86.290")
    assert by_code["heat_stress"].value_aux["temp_max_c"] == "40"


def test_heat_stress_needs_both_temperature_and_humidity() -> None:
    """Rather than compute a THI against an assumed humidity, emit nothing —
    the reading would look authoritative and be half invented."""
    on = date(2026, 7, 20)
    daily = {on: _day(on, tmax=40, tmean=32)}
    no_humidity = aggregate_radiation_wind_day([_ih("2026-07-20T12:00", wind_speed_m_s=2)])
    codes = {p.index_code for p in project_indices(on, daily, no_humidity)}
    assert "heat_stress" not in codes
