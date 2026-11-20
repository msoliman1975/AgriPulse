"""The build script's chunking and its reports.

The Job that runs this script has no log a person can read, so its
archive events are the only record. These tests pin what they say: one
progress event per chunk, and on a failure the step, the error and the
day to restart from.
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.modules.demo_history.runner import DayResult, ReplayReport, StepResult
from scripts import demo_build


class Events:
    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event: str, **details: Any) -> None:
        self.seen.append((event, details))


def _args(start: date, end: date, chunk: int = 7) -> argparse.Namespace:
    return argparse.Namespace(
        tenant_schema="tenant_x", scenario="s", start=start, end=end, chunk_days=chunk
    )


def _report(start: date, end: date, *, fail: bool = False) -> ReplayReport:
    at = datetime(start.year, start.month, start.day, 10, tzinfo=UTC)
    step = StepResult(
        name="recommendations.evaluate",
        at=at,
        counts=None if fail else {"blocks_processed": 36},
        error="RuntimeError: boom" if fail else None,
    )
    rep = ReplayReport(tenant_schema="tenant_x", start=start, end=end)
    rep.days.append(DayResult(day=start, steps=(step,)))
    return rep


def test_one_progress_event_per_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[date, date]] = []

    def fake_replay(**kw: Any) -> ReplayReport:
        calls.append((kw["start"], kw["end"]))
        return _report(kw["start"], kw["end"])

    monkeypatch.setattr(demo_build, "replay", fake_replay)
    events = Events()

    ok = demo_build._replay(_args(date(2024, 9, 29), date(2024, 10, 14)), events)  # type: ignore[arg-type]

    assert ok
    assert calls == [
        (date(2024, 9, 29), date(2024, 10, 5)),
        (date(2024, 10, 6), date(2024, 10, 12)),
        (date(2024, 10, 13), date(2024, 10, 14)),
    ]
    names = [e for e, _ in events.seen]
    assert names == ["replay_progress"] * 3 + ["replay_finished"]
    assert events.seen[-1][1]["totals"] == {"recommendations.evaluate": {"blocks_processed": 108}}


def test_a_failed_chunk_stops_and_names_the_restart_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_replay(**kw: Any) -> ReplayReport:
        return _report(kw["start"], kw["end"], fail=kw["start"] == date(2024, 10, 6))

    monkeypatch.setattr(demo_build, "replay", fake_replay)
    events = Events()

    ok = demo_build._replay(_args(date(2024, 9, 29), date(2024, 10, 30)), events)  # type: ignore[arg-type]

    assert not ok
    event, details = events.seen[-1]
    assert event == "replay_failed"
    assert details["restart_from"] == "2024-10-06"
    assert details["step"] == "recommendations.evaluate"
    assert "boom" in details["error"]


def test_replay_modes_need_a_range() -> None:
    with pytest.raises(SystemExit):
        demo_build._parse_args(["--tenant-schema", "t", "--scenario", "s", "--mode", "replay"])
    args = demo_build._parse_args(
        ["--tenant-schema", "t", "--scenario", "s", "--mode", "incidents-dry-run"]
    )
    assert args.start is None


def test_medjool_scenario_steps_carry_its_policy_and_dated_edits() -> None:
    from app.modules.demo_history import people
    from app.modules.demo_history.scenarios import medjool_oasis

    steps = {s.name: s for s in demo_build.scenario_steps(medjool_oasis)}

    team = steps["demo.team_work"].run
    assert team.func is people.act_for_tenant  # type: ignore[attr-defined]
    assert team.keywords["policy"] is medjool_oasis.TEAM_POLICY  # type: ignore[attr-defined]
    irrigation = steps["demo.irrigation_work"].run
    assert irrigation.keywords["policy"] is medjool_oasis.TEAM_POLICY  # type: ignore[attr-defined]
    edits = steps["demo.attribute_changes"].run
    assert edits.keywords["changes"] == medjool_oasis.ATTRIBUTE_CHANGES  # type: ignore[attr-defined]


def test_a_scenario_without_a_policy_keeps_the_default_steps() -> None:
    class Bare:
        FARM_CODE = "X"
        INCIDENTS = ()

    from app.modules.demo_history.steps import DEMO_BUILD_STEPS

    assert demo_build.scenario_steps(Bare) == DEMO_BUILD_STEPS


def test_medjool_scenario_stays_inside_its_span_and_blocks() -> None:
    from app.modules.demo_history.scenarios import medjool_oasis

    start, end = medjool_oasis.SPAN
    events: list[Any] = [*medjool_oasis.INCIDENTS, *medjool_oasis.WEATHER_INCIDENTS]
    assert len({e.code for e in events}) == len(events)
    for event in events:
        assert start <= event.start
        assert event.gone <= end
    for incident in medjool_oasis.INCIDENTS:
        assert set(incident.blocks) <= {"M2", "M5", "M28", "M31"}
    for change in medjool_oasis.ATTRIBUTE_CHANGES:
        assert start <= change.on <= end
    # The blocks must exist on the first replayed day, and before the copied
    # history begins, or the sweeps find nothing.
    assert date(2023, 8, 17) >= medjool_oasis.ACTIVE_FROM


def test_medjool_water_events_reach_the_water_tree() -> None:
    """The water tree reads SMI as a block value and targets sandy blocks.

    A partial incident moves a block row by its share of cells, so an SMI
    shift on a subset of cells would barely move the reading the tree sees.
    """
    from app.modules.demo_history.scenarios import medjool_oasis

    soil = [i for i in medjool_oasis.INCIDENTS if any(s.index_code == "smi" for s in i.shifts)]
    assert len(soil) >= 6
    for incident in soil:
        assert incident.cells == "all", incident.code
        assert set(incident.blocks) <= {"M2", "M28", "M31"}, incident.code
        for shift in incident.shifts:
            if shift.index_code == "smi":
                assert shift.mode == "set"
                assert shift.value < 0.16, incident.code
        # Landsat passes every 8 days: the full-strength window must hold one.
        assert (incident.until - incident.full).days >= 2


def test_attribute_changes_do_nothing_on_other_days() -> None:
    from app.modules.demo_history import people
    from app.shared import clock

    change = people.AttributeChange(
        on=date(2026, 3, 1), block="M5", attributes={"palm_phase": "bearing"}
    )
    with clock.simulate(datetime(2026, 2, 28, 15, tzinfo=UTC)):
        assert people.attribute_changes_for_tenant("tenant_x", (change,)) == {
            "attribute_changes": 0
        }
