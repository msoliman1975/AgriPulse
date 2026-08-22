"""Every Celery task entry point must drop the engine when it finishes.

A Celery task body is a sync shim over async code, so each one runs
`asyncio.run` and gets a fresh event loop. The engine and its pooled asyncpg
connections are process-wide and outlive that loop. A task that returns
without disposing leaves a connection bound to a closed loop, and the next
database task in the same pool process dies on it:

    RuntimeError: ... got Future ... attached to a different loop

The failure lands on the *next* task, never on the one that caused it, which
is what makes it so hard to attribute by reading a traceback. Observed on
production 2026-08-21: `iam.reconcile_keycloak` skipped the dispose at 18:59
and `integrations_health.check_failure_streaks` was the task that raised at
19:04 in the same pool process. Both had been shipped and running for months.

This test reads the source rather than executing anything, because the bug is
a property of how a module is written, not of what one call does. A runtime
test would need two tasks, two loops and one shared pool to reproduce it.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules"

# A module is safe if it routes its loop through the shared helper, or if it
# has its own runner that disposes. The second form is the older local
# `_run_async` / `_run_task` pattern, still present in twelve modules.
_SAFE_MARKERS = ("run_task_async", "dispose_engine")


def _task_modules() -> list[Path]:
    """Every module that defines at least one Celery task."""
    out = []
    for path in MODULES_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "shared_task" in text and "asyncio.run(" in text:
            out.append(path)
    return sorted(out)


def test_there_are_task_modules_to_check() -> None:
    """Guard the guard. If the discovery predicate silently stops matching,
    every assertion below passes over an empty list and this file becomes
    decoration."""
    assert len(_task_modules()) >= 10


def test_every_task_module_disposes_the_engine() -> None:
    offenders = []
    for path in _task_modules():
        text = path.read_text(encoding="utf-8")
        if not any(marker in text for marker in _SAFE_MARKERS):
            offenders.append(str(path.relative_to(MODULES_ROOT.parent.parent)))

    assert not offenders, (
        "These modules run a Celery task through asyncio.run without disposing "
        "the engine. The next database task in the same pool process will fail "
        "with 'got Future attached to a different loop':\n    "
        + "\n    ".join(offenders)
        + "\n\nRoute the call through app.shared.db.session.run_task_async."
    )


def test_no_task_body_calls_asyncio_run_directly() -> None:
    """The stronger form: a `@shared_task` function must not call
    `asyncio.run` in its own body.

    A module can satisfy the check above by importing a disposing helper and
    then still calling `asyncio.run` directly somewhere. This walks the AST so
    the two cannot drift apart.
    """
    offenders = []
    for path in _task_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any("shared_task" in ast.dump(dec) for dec in node.decorator_list)
            if not decorated:
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "run"
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "asyncio"
                ):
                    offenders.append(f"{path.relative_to(MODULES_ROOT.parent.parent)}::{node.name}")

    assert not offenders, (
        "These Celery task bodies call asyncio.run directly instead of a "
        "runner that disposes the engine:\n    " + "\n    ".join(offenders)
    )
