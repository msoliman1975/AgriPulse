"""Every task Beat schedules must be registered on the worker that runs it.

This exists because `recommendations.evaluate_sweep` was not, for the whole
life of the recommendations module. `_TASK_PACKAGES` listed
`app.modules.recommendations` -- the package -- and Celery's `include=`
imports the literal module name without recursing into it. The package's
`__init__.py` is a docstring, so `tasks.py` was never imported, the
`@shared_task` decorators never ran, and the task never reached the registry.

Nothing failed loudly. Beat dispatched the sweep every hour and the light
worker answered "Received unregistered task of type ... KeyError" into its
log, then carried on. The queue drained, the pod stayed Ready, no alert
fired, and no decision tree was ever evaluated by the sweep in production.

A wrong queue fails the same silent way: Beat routes by `options.queue`, so
a task registered only on `heavy` but scheduled onto `light` is dispatched
into a queue whose consumer has never heard of it.

So both halves are asserted here: the name resolves, and it resolves on the
queue Beat sends it to.
"""

from __future__ import annotations

import importlib

import pytest

from workers.celery_factory import _TASK_PACKAGES, QueueName, build_celery


def _registry(queue: QueueName) -> set[str]:
    """Task names a worker on ``queue`` would answer to.

    `include=` is lazy -- Celery imports those modules when the worker boots,
    not when the app object is built -- so building the app and reading
    `app.tasks` returns almost nothing. The modules are imported here for the
    same effect, which is also what makes this a unit test: no broker, no
    worker, no network.
    """
    app = build_celery(queue)
    for module in _TASK_PACKAGES:
        importlib.import_module(module)
    return {name for name in app.tasks if not name.startswith("celery.")}


def _beat_schedule() -> dict[str, dict]:
    return dict(importlib.import_module("workers.beat.main").app.conf.beat_schedule)


_SCHEDULE = _beat_schedule()


def test_beat_schedules_something() -> None:
    """Guards the two tests below: an empty schedule would pass both."""
    assert _SCHEDULE


@pytest.mark.parametrize("entry", sorted(_SCHEDULE))
def test_scheduled_task_is_registered(entry: str) -> None:
    task = _SCHEDULE[entry]["task"]
    queue: QueueName = _SCHEDULE[entry].get("options", {}).get("queue", "light")
    registered = _registry(queue)
    assert task in registered, (
        f"Beat schedules {task!r} onto the {queue!r} queue, but no worker on "
        f"that queue registers it. Check that `_TASK_PACKAGES` names the "
        f"module holding its @shared_task decorator, not its package."
    )


def test_recommendation_tasks_are_registered_on_light() -> None:
    """The three that were dead. Named individually rather than left to the
    schedule sweep above, because `evaluate_for_tenant` is dispatched by the
    sweep rather than by Beat, so no schedule entry would cover it."""
    registered = _registry("light")
    for task in (
        "recommendations.evaluate_sweep",
        "recommendations.evaluate_for_tenant",
        "recommendations.prune_eval_runs",
    ):
        assert task in registered


def test_no_task_package_is_a_bare_package_that_owns_tasks() -> None:
    """The shape of the original bug, caught at the list rather than at the
    schedule. A package entry is fine only when it has no `tasks` submodule
    to miss -- `audit` and `notifications` are listed that way on purpose."""
    offenders = []
    for name in _TASK_PACKAGES:
        module = importlib.import_module(name)
        if not hasattr(module, "__path__"):
            continue  # a module, not a package: nothing to recurse into
        try:
            importlib.import_module(f"{name}.tasks")
        except ModuleNotFoundError:
            continue
        offenders.append(name)
    assert offenders == [], (
        f"{offenders} are listed as packages but own a `tasks` submodule that "
        f"`include=` will not import. Name the submodule instead."
    )
