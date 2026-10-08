"""The expected end of a block crop's stage, by advance mode."""

from __future__ import annotations

from datetime import date

from app.modules.investors.stage_dates import stage_expected_end

TODAY = date(2026, 10, 8)


def test_calendar_stage_ends_this_year() -> None:
    advance = {"mode": "calendar_doy", "start_doy": "09-16", "end_doy": "11-15"}
    assert stage_expected_end(advance, planting_date=None, today=TODAY) == date(2026, 11, 15)


def test_calendar_stage_that_wraps_the_year_ends_next_year() -> None:
    advance = {"mode": "calendar_doy", "start_doy": "12-01", "end_doy": "01-31"}
    assert stage_expected_end(advance, planting_date=None, today=date(2026, 12, 20)) == date(
        2027, 1, 31
    )


def test_days_from_planting_counts_from_the_planting_date() -> None:
    advance = {"mode": "days_from_planting", "start_day": 0, "end_day": 30}
    assert stage_expected_end(advance, planting_date=date(2026, 9, 20), today=TODAY) == date(
        2026, 10, 20
    )


def test_manual_and_heat_unit_stages_have_no_date() -> None:
    assert stage_expected_end({"mode": "manual"}, planting_date=None, today=TODAY) is None
    gdd = {"mode": "gdd_from_planting", "start_gdd": 0, "end_gdd": 500}
    assert stage_expected_end(gdd, planting_date=date(2026, 1, 1), today=TODAY) is None
    assert stage_expected_end(None, planting_date=None, today=TODAY) is None
