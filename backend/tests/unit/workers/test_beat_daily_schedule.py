"""Daily Beat tasks run at a fixed clock time, not 24 h after each restart.

Beat's schedule file lives in /tmp, so a restart (every workers deploy)
forgets the last run. A 86400-second interval then restarts its 24-hour wait
on every deploy and, with deploys more often than daily, never fires: blocks
never advanced their growth stage. A crontab is due at its clock time
regardless of restarts.
"""

from __future__ import annotations

from celery.schedules import crontab

from workers.beat.main import _daily_at, app

_DAILY = (
    "phenology.advance_growth_stages",
    "weather.compute_risk_daily_sweep",
    "weather.compute_spi_sweep",
    "recommendations.prune_eval_runs",
    "grid.cleanup_superseded_grids",
)


def test_daily_tasks_are_crontabs_with_default_settings() -> None:
    schedule = app.conf.beat_schedule
    for name in _DAILY:
        assert isinstance(schedule[name]["schedule"], crontab), name


def test_daily_tasks_run_at_distinct_times() -> None:
    schedule = app.conf.beat_schedule
    times = {
        (tuple(sorted(schedule[n]["schedule"].hour)), tuple(sorted(schedule[n]["schedule"].minute)))
        for n in _DAILY
    }
    assert len(times) == len(_DAILY)


def test_a_shortened_interval_is_kept() -> None:
    assert _daily_at(600, hour=0, minute=15) == 600.0
    assert isinstance(_daily_at(86400, hour=0, minute=15), crontab)
