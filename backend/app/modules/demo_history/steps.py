"""The ordered work of one simulated day.

Each step names a per-tenant task function that the scheduler also calls in
production. The list and its order come from `workers/beat/main.py`; read
that file before changing anything here.

Two things are deliberately absent.

Imagery acquisition is not a step. The base scenes and index rows come from
the historical backfill, which ran once against the real provider for real
dates. Re-fetching them under a moved clock would ask a provider for a date
it has already served and would spend quota for no new data.

Weather fetching is not a step either, for the same reason.

The hour on each step is not decoration. Rows written by one day all carry
different times of day, which is what the past looks like when a person
reads it. It also keeps the order inside a day visible in the data: a
recommendation is stamped after the index refresh that produced its input.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.modules.farms import phenology_tasks
from app.modules.grid import tasks as grid_tasks
from app.modules.indices import tasks as indices_tasks
from app.modules.irrigation import tasks as irrigation_tasks
from app.modules.recommendations import tasks as recommendation_tasks
from app.modules.weather import tasks as weather_tasks

# Monday, to match how a person reads "weekly".
_WEEKLY_ON = 0


@dataclass(frozen=True)
class Step:
    """One task call inside one simulated day.

    `run` takes the tenant schema and returns whatever the task returns.
    Every task in the list returns a mapping of counts, and the runner
    keeps those counts so a silent zero can be found afterwards.

    `weekday` restricts the step to one day of the week. `None` means every
    day.
    """

    name: str
    hour: int
    run: Callable[[str], Mapping[str, Any]]
    weekday: int | None = None

    def due_on(self, weekday: int) -> bool:
        return self.weekday is None or self.weekday == weekday


DAILY_STEPS: tuple[Step, ...] = (
    # Growth stage first. Every later step reads the stage, and a tree that
    # targets a stage answers differently on the day a block advances.
    Step("phenology.advance", 5, phenology_tasks.advance_for_tenant),
    # The index continuous aggregates are real-time views with a
    # materialisation threshold, so a backfilled day stays invisible to
    # readers until this runs. Without it the trees read no index at all.
    Step("indices.refresh_caggs", 6, indices_tasks.refresh_index_caggs_for_tenant),
    # Weekly climatology. A z-score needs a baseline, and the baseline has
    # to grow with the simulated history rather than sit at its build-day
    # value for the whole span.
    Step(
        "indices.recompute_baselines",
        6,
        indices_tasks.recompute_baselines_for_tenant,
        weekday=_WEEKLY_ON,
    ),
    Step(
        "weather.recompute_baselines",
        6,
        weather_tasks.recompute_weather_baselines_for_tenant,
        weekday=_WEEKLY_ON,
    ),
    Step("weather.compute_risk", 7, weather_tasks.compute_weather_risk_for_tenant),
    Step("weather.compute_spi", 7, weather_tasks.compute_spi_for_tenant),
    # Yesterday's water balance. The task resolves its own target date from
    # the clock, so a moved clock moves the row it writes.
    Step("irrigation.water_balance", 8, irrigation_tasks.water_balance_for_tenant),
    Step("irrigation.generate", 8, irrigation_tasks.generate_for_tenant),
    Step("grid.detect_anomalies", 9, grid_tasks.detect_anomalies_for_tenant),
    # Last, because it reads everything the earlier steps wrote.
    Step("recommendations.evaluate", 10, recommendation_tasks.evaluate_for_tenant),
)


def steps_for(weekday: int, steps: tuple[Step, ...] = DAILY_STEPS) -> list[Step]:
    """Return the steps due on `weekday`, in the order they run.

    Steps sharing an hour keep their declared order, so the list above
    reads as the running order.
    """
    due = [(position, step) for position, step in enumerate(steps) if step.due_on(weekday)]
    due.sort(key=lambda pair: (pair[1].hour, pair[0]))
    return [step for _, step in due]
