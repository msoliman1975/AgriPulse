"""The allowlist is the security model, so it gets its own guard.

``task_registry._validate()`` runs at import and would already have raised on
a bad entry; these assertions exist so the *reason* survives a refactor that
moves or weakens that check.
"""

from __future__ import annotations

from app.modules.platform_admins.task_registry import BY_NAME, TRIGGERABLE


def test_no_sweep_or_destructive_tasks_are_triggerable() -> None:
    for task in TRIGGERABLE:
        assert not task.name.endswith("_sweep"), f"{task.name} walks every active tenant"
        assert not task.name.startswith("purge."), f"{task.name} is irreversible"


def test_tenant_schema_is_never_a_caller_supplied_param() -> None:
    """It is filled in from the resolved tenant; accepting it would let a
    caller aim a task at a tenant other than the one it named."""
    for task in TRIGGERABLE:
        assert "tenant_schema" not in task.accepted_params


def test_names_are_unique() -> None:
    assert len(BY_NAME) == len(TRIGGERABLE)


# Importing each module is what registers its tasks with the Celery app. Done
# through importlib rather than plain imports so a linter cannot decide the
# bindings are unused and strip the registration away.
_TASK_MODULES = (
    "app.modules.farms.phenology_tasks",
    "app.modules.grid.tasks",
    "app.modules.indices.tasks",
    "app.modules.irrigation.tasks",
    "app.modules.recommendations.tasks",
    "app.modules.weather.tasks",
)


def _registered_tasks() -> dict[str, object]:
    import importlib

    from celery import current_app

    for module in _TASK_MODULES:
        importlib.import_module(module)
    return dict(current_app.tasks)


def test_every_triggerable_task_is_a_registered_celery_task() -> None:
    """A typo'd name would dispatch into a queue nothing consumes and the
    caller would see an accepted 202 for work that never happens."""
    registered = _registered_tasks()
    missing = sorted(t.name for t in TRIGGERABLE if t.name not in registered)
    assert not missing, f"not registered with Celery: {missing}"


def test_every_triggerable_task_stores_its_result() -> None:
    """Being triggerable is only half of it — the run has to be observable.

    ``GET /admin/tasks/runs/{id}`` reads Celery's ``AsyncResult``. A task
    carrying ``ignore_result=True`` stores nothing, so that endpoint reports
    PENDING forever even after the task has succeeded, which is
    indistinguishable from a task that never started. Measured on production:
    ``indices.refresh_index_caggs_for_tenant`` succeeded in 0.16 s while the
    caller polled it as PENDING for 480 s and then gave up.

    Most tasks in this codebase set ``ignore_result=True`` on purpose and
    should keep it. The allowlisted ones are the exception, and this is what
    stops the next task added to the allowlist arriving unobservable.
    """
    registered = _registered_tasks()
    unobservable = sorted(
        t.name for t in TRIGGERABLE if getattr(registered.get(t.name), "ignore_result", False)
    )
    assert not unobservable, (
        "triggerable but the result is never stored, so a run reports PENDING "
        f"forever: {unobservable}"
    )
