"""Pure-function tests for the phenology stage resolver (PR-C1)."""

from __future__ import annotations

from datetime import date

from app.modules.farms.phenology_advance import stage_for_date


def _cal(code: str, order: int, start: str, end: str) -> dict:
    return {
        "code": code,
        "order": order,
        "advance": {"mode": "calendar_doy", "start_doy": start, "end_doy": end},
    }


def _days(code: str, order: int, start: int, end: int) -> dict:
    return {
        "code": code,
        "order": order,
        "advance": {"mode": "days_from_planting", "start_day": start, "end_day": end},
    }


PERENNIAL = [
    _cal("pre_flowering", 1, "12-01", "01-31"),  # wraps year boundary
    _cal("flowering", 2, "02-01", "03-15"),
    _cal("fruit_development", 4, "05-01", "07-15"),
]


def test_perennial_calendar_in_window() -> None:
    s = stage_for_date(PERENNIAL, is_perennial=True, planting_date=None, today=date(2026, 2, 20))
    assert s == "flowering"


def test_perennial_wraparound_window_matches_both_tails() -> None:
    # December and January both fall in the 12-01 -> 01-31 window.
    dec = stage_for_date(PERENNIAL, is_perennial=True, planting_date=None, today=date(2026, 12, 15))
    jan = stage_for_date(PERENNIAL, is_perennial=True, planting_date=None, today=date(2026, 1, 10))
    assert dec == "pre_flowering"
    assert jan == "pre_flowering"


def test_perennial_no_window_matches_returns_none() -> None:
    # April falls in no defined window above.
    assert (
        stage_for_date(PERENNIAL, is_perennial=True, planting_date=None, today=date(2026, 4, 10))
        is None
    )


def test_highest_order_wins_on_overlap() -> None:
    overlapping = [_cal("a", 1, "01-01", "12-31"), _cal("b", 5, "06-01", "06-30")]
    s = stage_for_date(overlapping, is_perennial=True, planting_date=None, today=date(2026, 6, 15))
    assert s == "b"


ANNUAL = [
    _days("emergence", 1, 0, 20),
    _days("vegetative", 2, 20, 45),
    _days("tuber_bulking", 4, 65, 100),
]


def test_annual_days_from_planting_window() -> None:
    plant = date(2026, 3, 1)
    s = stage_for_date(ANNUAL, is_perennial=False, planting_date=plant, today=date(2026, 3, 25))
    assert s == "vegetative"  # day 24


def test_annual_needs_planting_date() -> None:
    assert (
        stage_for_date(ANNUAL, is_perennial=False, planting_date=None, today=date(2026, 3, 25))
        is None
    )


def test_manual_mode_never_matches() -> None:
    stages = [{"code": "x", "order": 1, "advance": {"mode": "manual"}}]
    assert (
        stage_for_date(stages, is_perennial=True, planting_date=None, today=date(2026, 6, 1))
        is None
    )


def test_gdd_skipped_without_cumulative() -> None:
    stages = [
        {
            "code": "g",
            "order": 1,
            "advance": {"mode": "gdd_from_planting", "start_gdd": 0, "end_gdd": 500},
        }
    ]
    plant = date(2026, 3, 1)
    assert (
        stage_for_date(stages, is_perennial=False, planting_date=plant, today=date(2026, 3, 10))
        is None
    )
    # With a cumulative value in range, it matches.
    assert (
        stage_for_date(
            stages,
            is_perennial=False,
            planting_date=plant,
            today=date(2026, 3, 10),
            gdd_cumulative=120.0,
        )
        == "g"
    )


def test_mode_mismatch_for_cycle_is_ignored() -> None:
    # An annual-mode stage on a perennial evaluation never matches.
    assert (
        stage_for_date(
            ANNUAL, is_perennial=True, planting_date=date(2026, 3, 1), today=date(2026, 3, 25)
        )
        is None
    )
