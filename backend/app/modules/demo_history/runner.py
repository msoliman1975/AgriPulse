"""Walk a date range one simulated day at a time.

    report = replay(tenant_schema="tenant_demo_build", start=date(2026, 1, 1), end=date(2026, 6, 30))

For each day the runner moves the clock to that day, runs the steps due on
it, and records what each step returned. The clock is moved with
`clock.simulate`, which sets the Python side and, through the session hook,
the Postgres side as well. Every row those steps write carries the
simulated instant.

Three guards stand in front of the loop, because this writes past
timestamps into real tables and the damage is not obvious afterwards.

1. The tenant schema must start with the configured build prefix. An empty
   prefix, which is the default everywhere, means no tenant qualifies and
   the runner cannot start at all. That is the setting production runs on.
2. The range must be in the past. Replaying into the future writes rows
   the product would later write itself.
3. A step that raises stops the run by default. A silent zero is the known
   failure of this kind of work, and continuing past an error produces
   exactly that.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.demo_history.steps import DAILY_STEPS, Step, steps_for
from app.shared import clock

_log = get_logger(__name__)

__all__ = ["DayResult", "ReplayReport", "StepResult", "replay"]


class ReplayNotAllowedError(RuntimeError):
    """The run was refused before any row was written."""


@dataclass(frozen=True)
class StepResult:
    """What one step did on one day."""

    name: str
    at: datetime
    counts: Mapping[str, Any] | None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class DayResult:
    day: date
    steps: tuple[StepResult, ...]

    @property
    def failed(self) -> bool:
        return any(step.failed for step in self.steps)


@dataclass
class ReplayReport:
    """The whole run, kept so a silent zero can be found afterwards."""

    tenant_schema: str
    start: date
    end: date
    days: list[DayResult] = field(default_factory=list)

    @property
    def failed_steps(self) -> list[StepResult]:
        return [step for day in self.days for step in day.steps if step.failed]

    def totals(self) -> dict[str, dict[str, int]]:
        """Sum each step's integer counts across the whole run.

        A step whose totals are all zero produced nothing over the whole
        span. That is the number to read first.
        """
        summed: dict[str, dict[str, int]] = {}
        for day in self.days:
            for step in day.steps:
                bucket = summed.setdefault(step.name, {})
                for key, value in (step.counts or {}).items():
                    if isinstance(value, int) and not isinstance(value, bool):
                        bucket[key] = bucket.get(key, 0) + value
        return summed


def _days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _check_allowed(tenant_schema: str, start: date, end: date) -> None:
    prefix = get_settings().demo_history_build_schema_prefix
    if not prefix:
        raise ReplayNotAllowedError(
            "DEMO_HISTORY_BUILD_SCHEMA_PREFIX is empty, so no tenant may be "
            "replayed. This is the correct setting for production."
        )
    if not tenant_schema.startswith(prefix):
        raise ReplayNotAllowedError(
            f"{tenant_schema!r} is not a build tenant. Its schema must start " f"with {prefix!r}."
        )
    if start > end:
        raise ReplayNotAllowedError(f"start {start} is after end {end}.")
    today = clock.real_now().date()
    if end >= today:
        raise ReplayNotAllowedError(
            f"end {end} is not in the past. The last day a replay may write "
            f"is {today - timedelta(days=1)}."
        )


def replay(
    *,
    tenant_schema: str,
    start: date,
    end: date,
    steps: tuple[Step, ...] = DAILY_STEPS,
    stop_on_error: bool = True,
) -> ReplayReport:
    """Replay `tenant_schema` from `start` to `end`, both days included."""
    _check_allowed(tenant_schema, start, end)
    report = ReplayReport(tenant_schema=tenant_schema, start=start, end=end)
    _log.info(
        "demo_history_replay_start",
        tenant_schema=tenant_schema,
        start=start.isoformat(),
        end=end.isoformat(),
        days=(end - start).days + 1,
    )

    for day in _days(start, end):
        results: list[StepResult] = []
        for step in steps_for(day.weekday(), steps):
            at = datetime(day.year, day.month, day.day, step.hour, tzinfo=UTC)
            result = _run_step(step, at, tenant_schema)
            results.append(result)
            if result.failed and stop_on_error:
                report.days.append(DayResult(day=day, steps=tuple(results)))
                _log.error(
                    "demo_history_replay_stopped",
                    tenant_schema=tenant_schema,
                    day=day.isoformat(),
                    step=step.name,
                    error=result.error,
                )
                return report
        report.days.append(DayResult(day=day, steps=tuple(results)))

    _log.info(
        "demo_history_replay_done",
        tenant_schema=tenant_schema,
        days=len(report.days),
        failed_steps=len(report.failed_steps),
    )
    return report


def _run_step(step: Step, at: datetime, tenant_schema: str) -> StepResult:
    """Run one step with the clock moved to `at`.

    The clock is entered around the call and not around the whole day,
    because the task opens its own transaction and the Postgres setting is
    written when that transaction begins. Moving the clock after a
    transaction has started moves the Python side alone, with no error.
    """
    with clock.simulate(at):
        try:
            counts = step.run(tenant_schema)
        except Exception as exc:
            _log.warning(
                "demo_history_step_failed",
                step=step.name,
                at=at.isoformat(),
                error=str(exc),
            )
            return StepResult(
                name=step.name, at=at, counts=None, error=f"{type(exc).__name__}: {exc}"
            )
    _log.info("demo_history_step_done", step=step.name, at=at.isoformat(), counts=dict(counts))
    return StepResult(name=step.name, at=at, counts=counts)
