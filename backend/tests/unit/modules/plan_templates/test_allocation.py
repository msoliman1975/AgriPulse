"""Agri Operation PR 3: the saved-plan resolver (pure)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.modules.plan_templates.allocation import resolve_allocation

STAGES = [
    {"code": "flowering", "advance": {"mode": "calendar_doy", "start_doy": "02-15"}},
    {"code": "fruit_set", "advance": {"mode": "calendar_doy", "start_doy": "04-01"}},
]


def _act(code: str, activity_type: str, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": uuid4(),
        "code": code,
        "activity_type": activity_type,
        "anchor": "start",
        "offset_days": 0,
        "duration_days": 1,
        "title": code.title(),
        "product_name": "Manual product",
        "dosage": "Manual dose",
        "notes": "Manual note",
    }
    base.update(kw)
    return base


MANUAL = [
    _act("soil_prep-1", "soil_prep", offset_days=0),
    _act("fertilizing-1", "fertilizing", anchor="stage", stage_code="flowering", offset_days=7),
    _act("spraying-1", "spraying", anchor="stage", stage_code="fruit_set"),
]


def _resolve(**kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "activities": MANUAL,
        "milestones": [],
        "stages": STAGES,
        "block_start_date": date(2026, 1, 1),
        "planting_date": None,
        "is_perennial": True,
        "season_year": 2026,
        "excluded_codes": set(),
        "activity_edits": {},
        "custom_activities": [],
        "overrides": {},
    }
    args.update(kw)
    return resolve_allocation(**args)  # type: ignore[arg-type]


def test_manual_only_matches_the_anchor_rules() -> None:
    acts, skipped = _resolve()
    assert skipped == []
    by_key = {a.activity_key: a for a in acts}
    assert by_key["soil_prep-1"].scheduled_date == date(2026, 1, 1)
    assert by_key["fertilizing-1"].scheduled_date == date(2026, 2, 22)
    assert by_key["fertilizing-1"].anchored_stage_code == "flowering"
    assert by_key["spraying-1"].scheduled_date == date(2026, 4, 1)
    assert all(a.source == "template" and not a.date_overridden for a in acts)
    assert [a.scheduled_date for a in acts] == sorted(a.scheduled_date for a in acts)


def test_excluded_codes_are_left_out() -> None:
    acts, _ = _resolve(excluded_codes={"spraying-1"})
    assert {a.activity_key for a in acts} == {"soil_prep-1", "fertilizing-1"}


def test_edits_replace_only_the_fields_given() -> None:
    acts, _ = _resolve(activity_edits={"fertilizing-1": {"product_name": "Farm urea"}})
    fert = next(a for a in acts if a.activity_key == "fertilizing-1")
    assert fert.product_name == "Farm urea"
    assert fert.dosage == "Manual dose"
    other = next(a for a in acts if a.activity_key == "soil_prep-1")
    assert other.product_name == "Manual product"


def test_custom_activities_by_week_and_by_stage() -> None:
    acts, skipped = _resolve(
        custom_activities=[
            {"key": "custom:w3", "activity_type": "observation", "title": "Walk", "week": 3},
            {
                "key": "custom:st",
                "activity_type": "pruning",
                "title": "Tip",
                "anchor": "stage",
                "stage_code": "fruit_set",
                "offset_days": 3,
            },
            {
                "key": "custom:bad",
                "activity_type": "pruning",
                "title": "Nowhere",
                "anchor": "stage",
                "stage_code": "no_such_stage",
            },
        ]
    )
    by_key = {a.activity_key: a for a in acts}
    assert by_key["custom:w3"].scheduled_date == date(2026, 1, 15)
    assert by_key["custom:w3"].source == "custom"
    assert by_key["custom:w3"].template_activity_id is None
    assert by_key["custom:st"].scheduled_date == date(2026, 4, 4)
    assert by_key["custom:st"].anchored_stage_code == "fruit_set"
    assert [s["activity_key"] for s in skipped] == ["custom:bad"]


def test_overrides_move_dates_and_keep_the_default() -> None:
    acts, _ = _resolve(
        overrides={"spraying-1": "2026-04-10", "custom:w3": "2026-01-20"},
        custom_activities=[
            {"key": "custom:w3", "activity_type": "observation", "title": "Walk", "week": 3}
        ],
    )
    by_key = {a.activity_key: a for a in acts}
    assert by_key["spraying-1"].scheduled_date == date(2026, 4, 10)
    assert by_key["spraying-1"].default_date == date(2026, 4, 1)
    assert by_key["spraying-1"].date_overridden is True
    assert by_key["custom:w3"].scheduled_date == date(2026, 1, 20)
    assert by_key["soil_prep-1"].date_overridden is False


def test_custom_key_without_prefix_gets_one() -> None:
    acts, _ = _resolve(
        custom_activities=[{"key": "abc", "activity_type": "pruning", "title": "X", "week": 1}]
    )
    assert any(a.activity_key == "custom:abc" for a in acts)


# ---- Repeating tasks (public 0115): each time is its own task ----------------


def test_occurrence_offsets_spacing() -> None:
    from app.modules.plan_templates.allocation import occurrence_offsets

    # Once.
    assert occurrence_offsets(56, None, None) == [0]
    # 2x a week over 4 weeks: every 3-4 days, 8 times.
    assert occurrence_offsets(28, 2, "week") == [0, 3, 7, 10, 14, 17, 21, 24]
    # Daily for a week.
    assert occurrence_offsets(7, 7, "week") == [0, 1, 2, 3, 4, 5, 6]
    # Monthly over a year: 12 times, about a month apart.
    monthly = occurrence_offsets(365, 1, "month")
    assert len(monthly) == 12
    assert monthly[1] == 30
    assert monthly[-1] == 334
    # Twice a month over 91 days.
    assert occurrence_offsets(91, 2, "month") == [0, 15, 30, 45, 60, 76]
    # 2 times in the season, spread over the window.
    assert occurrence_offsets(35, 2, "season") == [0, 17]
    # A window shorter than the spacing still gets its first time.
    assert occurrence_offsets(5, 1, "month") == [0]


def test_a_repeating_task_is_scheduled_once_per_time() -> None:
    manual = [
        _act("irrigation-1", "irrigation", duration_days=21, repeat_count=1, repeat_unit="week"),
        _act("pruning-1", "pruning", duration_days=21),
    ]
    acts, _ = _resolve(activities=manual)
    irrigation = [a for a in acts if a.activity_code == "irrigation-1"]
    assert [a.activity_key for a in irrigation] == [
        "irrigation-1",
        "irrigation-1#2",
        "irrigation-1#3",
    ]
    assert [a.scheduled_date for a in irrigation] == [
        date(2026, 1, 1),
        date(2026, 1, 8),
        date(2026, 1, 15),
    ]
    assert [(a.occurrence, a.occurrences) for a in irrigation] == [(1, 3), (2, 3), (3, 3)]
    # Each time is a one-day job; a task done once keeps its window.
    assert {a.duration_days for a in irrigation} == {1}
    (pruning,) = (a for a in acts if a.activity_code == "pruning-1")
    assert (pruning.activity_key, pruning.duration_days, pruning.occurrences) == (
        "pruning-1",
        21,
        1,
    )


def test_each_time_moves_alone_and_edits_apply_to_every_time() -> None:
    manual = [
        _act("irrigation-1", "irrigation", duration_days=21, repeat_count=1, repeat_unit="week")
    ]
    acts, _ = _resolve(
        activities=manual,
        overrides={"irrigation-1#2": "2026-01-10"},
        activity_edits={"irrigation-1": {"notes": "Drip only"}},
    )
    by_key = {a.activity_key: a for a in acts}
    assert by_key["irrigation-1#2"].scheduled_date == date(2026, 1, 10)
    assert by_key["irrigation-1#2"].date_overridden is True
    assert by_key["irrigation-1#2"].default_date == date(2026, 1, 8)
    assert by_key["irrigation-1"].date_overridden is False
    assert {a.notes for a in acts} == {"Drip only"}
    # Leaving the task out leaves out every time.
    none, _ = _resolve(activities=manual, excluded_codes={"irrigation-1"})
    assert none == []


# ---- Stage dates and task windows (the calendar groups weeks by stage) -------


def test_stage_dates_follow_the_schedule_rule() -> None:
    from app.modules.plan_templates.allocation import stage_dates

    stages = [
        {
            "code": "flowering",
            "name_en": "Flowering",
            "advance": {"mode": "calendar_doy", "start_doy": "02-15"},
        },
        {
            "code": "fruit_set",
            "name_en": "Fruit set",
            "advance": {"mode": "calendar_doy", "start_doy": "04-01", "end_doy": "05-31"},
        },
    ]
    got = stage_dates(stages, is_perennial=True, planting_date=None, season_year=2026)
    assert [(s["code"], s["start_date"], s["end_date"]) for s in got] == [
        ("flowering", date(2026, 2, 15), date(2026, 3, 31)),
        ("fruit_set", date(2026, 4, 1), date(2026, 5, 31)),
    ]
    # An annual stage without a planting date has no date and is left out.
    annual = [{"code": "veg", "advance": {"mode": "days_from_planting", "start_day": 0}}]
    assert stage_dates(annual, is_perennial=False, planting_date=None, season_year=2026) == []


def test_each_time_carries_the_task_window() -> None:
    manual = [
        _act("irrigation-1", "irrigation", duration_days=21, repeat_count=1, repeat_unit="week"),
        _act("pruning-1", "pruning", duration_days=21),
    ]
    acts, _ = _resolve(activities=manual)
    windows = {(a.activity_key, a.window_start, a.window_end) for a in acts}
    assert ("irrigation-1#3", date(2026, 1, 1), date(2026, 1, 21)) in windows
    assert ("pruning-1", date(2026, 1, 1), date(2026, 1, 21)) in windows
