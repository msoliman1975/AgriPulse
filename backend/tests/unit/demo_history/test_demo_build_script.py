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
