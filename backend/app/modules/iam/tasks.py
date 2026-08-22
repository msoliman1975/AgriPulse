"""Celery tasks for the iam module.

Beat picks up `iam.reconcile_keycloak` from the schedule in
`workers/beat/main.py`. The body is a thin sync shim that runs the async
reconciler in a fresh event loop (Celery workers are sync).

The loop comes from ``run_task_async`` rather than a bare event-loop run,
because the engine has to be disposed when the task ends. See that
function for why skipping the dispose breaks the *next* task in the pool
rather than this one.
"""

from __future__ import annotations

from celery import shared_task

from app.core.logging import get_logger
from app.modules.iam.reconcile import run_keycloak_reconcile
from app.shared.db.session import run_task_async

_log = get_logger(__name__)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="iam.reconcile_keycloak",
    bind=False,
    ignore_result=True,
)
def reconcile_keycloak() -> dict[str, int]:
    """Run one DB -> Keycloak reconcile pass synchronously."""
    summary = run_task_async(run_keycloak_reconcile())
    _log.info("iam.reconcile_keycloak.summary", **summary)
    return summary
