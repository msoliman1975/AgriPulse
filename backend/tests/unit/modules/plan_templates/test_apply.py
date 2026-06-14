"""Pure-function tests for the plan-template apply resolver (PR-E2)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from app.modules.plan_templates.apply import resolve_schedule

_PERENNIAL_STAGES = [
    {
        "code": "post_harvest_flush",
        "order": 5,
        "advance": {"mode": "calendar_doy", "start_doy": "07-16", "end_doy": "10-31"},
    }
]
_ANNUAL_STAGES = [
    {
        "code": "tuber_bulking",
        "order": 4,
        "advance": {"mode": "days_from_planting", "start_day": 65, "end_day": 100},
    }
]


def _act(anchor: str, **kw) -> dict:
    base = {
        "id": uuid4(),
        "activity_type": "fertilizing",
        "anchor": anchor,
        "milestone_id": None,
        "stage_code": None,
        "offset_days": 0,
        "duration_days": 1,
        "product_name": None,
        "dosage": None,
        "notes": None,
        "start_time": None,
    }
    base.update(kw)
    return base


def test_start_anchor_offsets_from_block_start() -> None:
    acts = [_act("start", offset_days=3)]
    resolved, skipped = resolve_schedule(
        activities=acts,
        milestones=[],
        stages=None,
        block_start_date=date(2026, 3, 1),
        planting_date=None,
        is_perennial=False,
        season_year=2026,
    )
    assert not skipped
    assert resolved[0].scheduled_date == date(2026, 3, 4)


def test_milestone_anchor() -> None:
    mid = uuid4()
    acts = [_act("milestone", milestone_id=mid, offset_days=-2)]
    milestones = [{"id": mid, "day_from_start": 60}]
    resolved, _ = resolve_schedule(
        activities=acts,
        milestones=milestones,
        stages=None,
        block_start_date=date(2026, 3, 1),
        planting_date=None,
        is_perennial=False,
        season_year=2026,
    )
    # 2026-03-01 + (60 - 2) days = 2026-04-28
    assert resolved[0].scheduled_date == date(2026, 4, 28)


def test_stage_anchor_perennial_maps_doy_to_season_year() -> None:
    acts = [_act("stage", stage_code="post_harvest_flush", offset_days=7)]
    resolved, _ = resolve_schedule(
        activities=acts,
        milestones=[],
        stages=_PERENNIAL_STAGES,
        block_start_date=date(2026, 1, 1),
        planting_date=None,
        is_perennial=True,
        season_year=2026,
    )
    # 2026-07-16 + 7 days
    assert resolved[0].scheduled_date == date(2026, 7, 23)
    assert resolved[0].anchored_stage_code == "post_harvest_flush"


def test_stage_anchor_annual_from_planting() -> None:
    acts = [_act("stage", stage_code="tuber_bulking", offset_days=0)]
    resolved, _ = resolve_schedule(
        activities=acts,
        milestones=[],
        stages=_ANNUAL_STAGES,
        block_start_date=date(2026, 3, 1),
        planting_date=date(2026, 3, 1),
        is_perennial=False,
        season_year=2026,
    )
    # planting 2026-03-01 + 65 days
    assert resolved[0].scheduled_date == date(2026, 5, 5)


def test_stage_anchor_unknown_stage_is_skipped() -> None:
    acts = [_act("stage", stage_code="does_not_exist")]
    resolved, skipped = resolve_schedule(
        activities=acts,
        milestones=[],
        stages=_PERENNIAL_STAGES,
        block_start_date=date(2026, 1, 1),
        planting_date=None,
        is_perennial=True,
        season_year=2026,
    )
    assert not resolved
    assert skipped[0]["reason"] == "stage_not_in_phenology"


def test_stage_anchor_annual_without_planting_date_skipped() -> None:
    acts = [_act("stage", stage_code="tuber_bulking")]
    resolved, skipped = resolve_schedule(
        activities=acts,
        milestones=[],
        stages=_ANNUAL_STAGES,
        block_start_date=date(2026, 3, 1),
        planting_date=None,
        is_perennial=False,
        season_year=2026,
    )
    assert not resolved
    assert skipped[0]["reason"] == "stage_date_unresolvable"
