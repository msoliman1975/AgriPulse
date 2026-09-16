"""The replay loop: its guards, its order, and the clock it runs under.

No database. The steps here are fakes that record the clock they saw, which
is the one property the whole feature rests on: if the clock is not moved
while a step runs, every row that step writes carries today's date and
nothing reports an error.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.core.settings import get_settings
from app.modules.demo_history.runner import ReplayNotAllowedError, replay
from app.modules.demo_history.steps import Step, steps_for
from app.shared import clock

BUILD_SCHEMA = "tenant_demobuild_x"
LAST_WEEK = datetime.now(UTC).date() - timedelta(days=7)


@pytest.fixture(autouse=True)
def _allow_build_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_HISTORY_BUILD_SCHEMA_PREFIX", "tenant_demobuild")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class Recorder:
    """A fake step body that records the clock it ran under."""

    def __init__(self, name: str, counts: Mapping[str, Any] | None = None) -> None:
        self.name = name
        self.counts = counts or {"rows": 1}
        self.seen: list[datetime] = []
        self.schemas: list[str] = []

    def __call__(self, tenant_schema: str) -> Mapping[str, Any]:
        self.seen.append(clock.now())
        self.schemas.append(tenant_schema)
        return self.counts


def test_a_step_runs_with_the_clock_moved_to_the_simulated_day() -> None:
    body = Recorder("one")
    steps = (Step("one", 7, body),)

    replay(tenant_schema=BUILD_SCHEMA, start=LAST_WEEK, end=LAST_WEEK, steps=steps)

    assert body.seen == [datetime(LAST_WEEK.year, LAST_WEEK.month, LAST_WEEK.day, 7, tzinfo=UTC)]
    assert body.schemas == [BUILD_SCHEMA]


def test_the_clock_is_back_to_real_time_after_the_run() -> None:
    steps = (Step("one", 7, Recorder("one")),)

    replay(tenant_schema=BUILD_SCHEMA, start=LAST_WEEK, end=LAST_WEEK, steps=steps)

    assert clock.simulated_now() is None


def test_every_day_in_the_range_runs_once() -> None:
    body = Recorder("one")
    start = LAST_WEEK - timedelta(days=2)
    steps = (Step("one", 7, body),)

    report = replay(tenant_schema=BUILD_SCHEMA, start=start, end=LAST_WEEK, steps=steps)

    assert [day.day for day in report.days] == [
        start,
        start + timedelta(days=1),
        LAST_WEEK,
    ]
    assert len(body.seen) == 3


def test_a_weekly_step_runs_only_on_its_weekday() -> None:
    body = Recorder("weekly")
    monday = date(2026, 3, 2)
    assert monday.weekday() == 0
    steps = (Step("weekly", 6, body, weekday=0),)

    replay(
        tenant_schema=BUILD_SCHEMA,
        start=monday,
        end=monday + timedelta(days=6),
        steps=steps,
    )

    assert [seen.date() for seen in body.seen] == [monday]


def test_steps_run_in_hour_order_then_declared_order() -> None:
    order: list[str] = []

    def mark(name: str):
        def _run(tenant_schema: str) -> Mapping[str, Any]:
            order.append(name)
            return {}

        return _run

    steps = (
        Step("late", 10, mark("late")),
        Step("early_second", 6, mark("early_second")),
        Step("early_first", 6, mark("early_first")),
    )

    replay(tenant_schema=BUILD_SCHEMA, start=LAST_WEEK, end=LAST_WEEK, steps=steps)

    assert order == ["early_second", "early_first", "late"]


def test_a_failing_step_stops_the_run_and_names_itself() -> None:
    def boom(tenant_schema: str) -> Mapping[str, Any]:
        raise ValueError("no weather rows")

    after = Recorder("after")
    steps = (Step("boom", 6, boom), Step("after", 7, after))

    report = replay(
        tenant_schema=BUILD_SCHEMA,
        start=LAST_WEEK - timedelta(days=3),
        end=LAST_WEEK,
        steps=steps,
    )

    assert len(report.days) == 1
    assert after.seen == []
    assert [step.name for step in report.failed_steps] == ["boom"]
    assert report.failed_steps[0].error == "ValueError: no weather rows"


def test_stop_on_error_false_keeps_going_and_keeps_the_error() -> None:
    def boom(tenant_schema: str) -> Mapping[str, Any]:
        raise ValueError("no weather rows")

    steps = (Step("boom", 6, boom),)

    report = replay(
        tenant_schema=BUILD_SCHEMA,
        start=LAST_WEEK - timedelta(days=1),
        end=LAST_WEEK,
        steps=steps,
        stop_on_error=False,
    )

    assert len(report.days) == 2
    assert len(report.failed_steps) == 2


def test_totals_add_the_counts_across_the_run() -> None:
    steps = (Step("one", 7, Recorder("one", {"opened": 2, "skipped": True})),)

    report = replay(
        tenant_schema=BUILD_SCHEMA,
        start=LAST_WEEK - timedelta(days=2),
        end=LAST_WEEK,
        steps=steps,
    )

    # Booleans are not counts, so `skipped` is left out rather than added
    # as 3.
    assert report.totals() == {"one": {"opened": 6}}


def test_an_empty_prefix_refuses_every_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_HISTORY_BUILD_SCHEMA_PREFIX", "")
    get_settings.cache_clear()

    with pytest.raises(ReplayNotAllowedError, match="is empty"):
        replay(tenant_schema=BUILD_SCHEMA, start=LAST_WEEK, end=LAST_WEEK, steps=())


def test_a_tenant_outside_the_prefix_is_refused() -> None:
    with pytest.raises(ReplayNotAllowedError, match="not a build tenant"):
        replay(tenant_schema="tenant_bashayer", start=LAST_WEEK, end=LAST_WEEK, steps=())


def test_today_is_refused() -> None:
    today = datetime.now(UTC).date()

    with pytest.raises(ReplayNotAllowedError, match="not in the past"):
        replay(tenant_schema=BUILD_SCHEMA, start=today, end=today, steps=())


def test_a_backwards_range_is_refused() -> None:
    with pytest.raises(ReplayNotAllowedError, match="is after end"):
        replay(
            tenant_schema=BUILD_SCHEMA,
            start=LAST_WEEK,
            end=LAST_WEEK - timedelta(days=1),
            steps=(),
        )


def test_a_refused_run_writes_nothing() -> None:
    body = Recorder("one")

    with pytest.raises(ReplayNotAllowedError):
        replay(
            tenant_schema="tenant_bashayer",
            start=LAST_WEEK,
            end=LAST_WEEK,
            steps=(Step("one", 7, body),),
        )

    assert body.seen == []


def test_the_real_day_list_has_the_engine_last() -> None:
    """The recommendation sweep reads what the earlier steps wrote."""
    monday = date(2026, 3, 2)

    names = [step.name for step in steps_for(monday.weekday())]

    assert names[-1] == "recommendations.evaluate"
    assert names[0] == "phenology.advance"
    assert "indices.recompute_baselines" in names


def test_the_weekly_steps_are_absent_on_other_days() -> None:
    tuesday = date(2026, 3, 3)

    names = [step.name for step in steps_for(tuesday.weekday())]

    assert "indices.recompute_baselines" not in names
    assert "weather.recompute_baselines" not in names
    assert "recommendations.evaluate" in names
