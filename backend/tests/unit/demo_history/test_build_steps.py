"""The build tenant's day and the team's stable choices.

No database. The order matters because each step reads what the one
before it wrote: the forecast must exist before the trees read it, and
the team must act after the sweep that opened the card.
"""

from __future__ import annotations

from datetime import date

from app.modules.demo_history import people
from app.modules.demo_history.steps import DAILY_STEPS, DEMO_BUILD_STEPS, steps_for


def test_the_build_day_wraps_the_engine_steps() -> None:
    names = [s.name for s in steps_for(0, DEMO_BUILD_STEPS)]
    assert names[0] == "demo.hindcast_forecast"
    assert names[-1] == "demo.team_work"
    engine = [s.name for s in steps_for(0, DAILY_STEPS)]
    assert names[1:-1] == engine


def test_the_team_works_after_the_sweep() -> None:
    by_name = {s.name: s for s in DEMO_BUILD_STEPS}
    assert by_name["demo.team_work"].hour > by_name["recommendations.evaluate"].hour


def test_rolls_are_stable_and_in_range() -> None:
    first = people._roll("rec-1", "choice")
    assert first == people._roll("rec-1", "choice")
    assert first != people._roll("rec-2", "choice")
    assert 0 <= first < 1


def test_actions_land_in_working_hours() -> None:
    day = date(2025, 7, 14)
    for key in range(200):
        at = people._at(day, key, 7, 12)
        assert at.date() == day
        assert 7 <= at.hour < 12
