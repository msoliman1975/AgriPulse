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
