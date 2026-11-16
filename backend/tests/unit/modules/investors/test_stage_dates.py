"""The expected end of a block crop's stage, by advance mode."""

from __future__ import annotations

from datetime import date

from app.modules.investors.stage_dates import (
    expected_harvest_on,
    season_stages,
    stage_expected_end,
)

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


# ---- The season's stage list (build plan v2, PR 2) --------------------------


def _cal(code: str, order: int, start: str, end: str) -> dict[str, object]:
    return {
        "code": code,
        "name_en": code.title(),
        "name_ar": "ع",
        "order": order,
        "advance": {"mode": "calendar_doy", "start_doy": start, "end_doy": end},
    }


# The generic date palm calendar: the first stage wraps the new year.
DATE_PALM = [
    _cal("tamar", 7, "10-01", "11-30"),
    _cal("dormancy", 1, "12-01", "02-15"),
    _cal("pollination", 2, "02-16", "03-31"),
    _cal("rutab", 6, "09-01", "09-30"),
]


def test_calendar_season_is_laid_out_in_order_across_the_new_year() -> None:
    season = season_stages(DATE_PALM, planting_date=None, today=date(2026, 11, 16))
    assert [(s["code"], s["expected_start"], s["expected_end"]) for s in season] == [
        ("dormancy", date(2025, 12, 1), date(2026, 2, 15)),
        ("pollination", date(2026, 2, 16), date(2026, 3, 31)),
        ("rutab", date(2026, 9, 1), date(2026, 9, 30)),
        ("tamar", date(2026, 10, 1), date(2026, 11, 30)),
    ]
    assert season[0] == {
        "code": "dormancy",
        "name_en": "Dormancy",
        "name_ar": "ع",
        "expected_start": date(2025, 12, 1),
        "expected_end": date(2026, 2, 15),
    }


def test_a_new_season_starts_on_the_first_stage() -> None:
    season = season_stages(DATE_PALM, planting_date=None, today=date(2026, 12, 2))
    assert season[0]["expected_start"] == date(2026, 12, 1)
    assert season[-1]["expected_start"] == date(2027, 10, 1)


def test_days_from_planting_stages_count_from_planting() -> None:
    stages = [
        {
            "code": "emergence",
            "order": 1,
            "advance": {"mode": "days_from_planting", "start_day": 0, "end_day": 20},
        },
        {
            "code": "maturation",
            "order": 2,
            "advance": {"mode": "days_from_planting", "start_day": 100, "end_day": 120},
        },
    ]
    season = season_stages(stages, planting_date=date(2026, 3, 1), today=TODAY)
    assert season[1]["expected_start"] == date(2026, 6, 9)
    assert expected_harvest_on(season) == date(2026, 6, 9)
    # No planting date: the stages stay, undated.
    undated = season_stages(stages, planting_date=None, today=TODAY)
    assert [s["expected_start"] for s in undated] == [None, None]


def test_gdd_and_manual_stages_have_no_dates() -> None:
    stages = [
        {"code": "a", "order": 1, "advance": {"mode": "manual"}},
        {
            "code": "b",
            "order": 2,
            "advance": {"mode": "gdd_from_planting", "start_gdd": 0, "end_gdd": 9},
        },
    ]
    season = season_stages(stages, planting_date=date(2026, 1, 1), today=TODAY)
    assert all(s["expected_start"] is None and s["expected_end"] is None for s in season)


def test_harvest_stage_preference() -> None:
    medjool = [_cal("rutab", 6, "07-30", "08-26"), _cal("harvest", 8, "09-10", "10-14")]
    season = season_stages(medjool, planting_date=None, today=TODAY)
    assert expected_harvest_on(season) == date(2026, 9, 10)
    generic = season_stages(DATE_PALM, planting_date=None, today=date(2026, 11, 16))
    assert expected_harvest_on(generic) == date(2026, 9, 1)
    assert (
        expected_harvest_on(
            season_stages([_cal("bloom", 1, "03-01", "04-01")], planting_date=None, today=TODAY)
        )
        is None
    )


def test_bad_input_gives_an_empty_or_undated_list() -> None:
    assert season_stages(None, planting_date=None, today=TODAY) == []
    assert season_stages({"stages": []}, planting_date=None, today=TODAY) == []
    assert season_stages([{"no_code": 1}, "x"], planting_date=None, today=TODAY) == []
    broken = season_stages(
        [{"code": "x", "advance": {"mode": "calendar_doy", "start_doy": "nope", "end_doy": "1"}}],
        planting_date=None,
        today=TODAY,
    )
    assert broken[0]["expected_start"] is None
