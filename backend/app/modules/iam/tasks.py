"""Celery tasks for the iam module.

Beat picks up `iam.reconcile_keycloak` from the schedule in
`workers/beat/main.py`. The body is a thin sync shim that runs the async
reconciler in a fresh event loop (Celery workers are sync).

See `farms/tasks.py` for why this uses `run_db_task` rather than
`asyncio.run`: the reconciler reads the database, and not disposing the
engine broke the next task in the same worker process.
"""

from __future__ import annotations

from celery import shared_task

from app.core.logging import get_logger
from app.modules.iam.reconcile import run_keycloak_reconcile
from app.shared.db.task_runner import run_db_task

_log = get_logger(__name__)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="iam.reconcile_keycloak",
    bind=False,
    ignore_result=True,
)
def reconcile_keycloak() -> dict[str, int]:
    """Run one DB -> Keycloak reconcile pass synchronously."""
    summary = run_db_task(run_keycloak_reconcile())
    _log.info("iam.reconcile_keycloak.summary", **summary)
    return summary
