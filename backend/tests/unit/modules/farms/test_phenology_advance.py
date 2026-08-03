"""Pure-function tests for the phenology stage resolver (PR-C1)."""

from __future__ import annotations

from datetime import date

from app.modules.farms.phenology_advance import needs_gdd, stage_for_date


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


# ---- GDD advance mode (W5) -------------------------------------------


def _gdd(code: str, order: int, start: int, end: int) -> dict:
    return {
        "code": code,
        "order": order,
        "advance": {"mode": "gdd_from_planting", "start_gdd": start, "end_gdd": end},
    }


GDD_CALENDAR = [
    _gdd("emergence", 1, 0, 200),
    _gdd("vegetative", 2, 200, 600),
    _gdd("bulking", 3, 600, 1200),
]

PLANTED = date(2026, 3, 1)
LATER = date(2026, 5, 1)


def _gdd_stage(total: float | None) -> str | None:
    return stage_for_date(
        GDD_CALENDAR,
        is_perennial=False,
        planting_date=PLANTED,
        today=LATER,
        gdd_cumulative=total,
    )


def test_gdd_windows_are_start_inclusive_end_exclusive() -> None:
    # The boundary matters: at exactly 200 the crop has left emergence.
    assert _gdd_stage(199.9) == "emergence"
    assert _gdd_stage(200.0) == "vegetative"
    assert _gdd_stage(599.9) == "vegetative"
    assert _gdd_stage(600.0) == "bulking"


def test_gdd_beyond_the_last_window_holds_the_stage() -> None:
    # Past the end of the calendar nothing matches, so the caller leaves
    # the block where it is rather than resetting it.
    assert _gdd_stage(5000.0) is None


def test_gdd_without_weather_history_holds_the_stage() -> None:
    # `load_gdd_since` returns None when the farm has no derived rows;
    # the block must hold its stage rather than snapping to emergence.
    assert _gdd_stage(None) is None


def test_zero_accumulated_heat_is_a_real_answer() -> None:
    # A farm with weather rows but no accumulated heat is genuinely at
    # the first stage — distinct from "no data", which returns None.
    assert _gdd_stage(0.0) == "emergence"


def test_needs_gdd_detects_a_heat_driven_calendar() -> None:
    assert needs_gdd(GDD_CALENDAR) is True
    assert needs_gdd([_gdd("g", 1, 0, 100), _days("d", 2, 0, 10)]) is True


def test_needs_gdd_is_false_for_calendars_seeded_today() -> None:
    # Mango/date palm (calendar_doy) and potato (days_from_planting) must
    # not trigger the farm-id resolution or the GDD query.
    assert needs_gdd(PERENNIAL) is False
    assert needs_gdd(ANNUAL) is False
    assert needs_gdd([]) is False
    assert needs_gdd([{"code": "m", "order": 1, "advance": {"mode": "manual"}}]) is False
    assert needs_gdd([{"code": "x", "order": 1}]) is False
