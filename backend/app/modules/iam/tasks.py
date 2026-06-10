"""Celery tasks for the iam module.

Beat picks up `iam.reconcile_keycloak` from the schedule in
`workers/beat/main.py`. The body is a thin sync shim that runs the async
reconciler in a fresh event loop (Celery workers are sync).
"""

from __future__ import annotations

import asyncio

from celery import shared_task

from app.core.logging import get_logger
from app.modules.iam.reconcile import run_keycloak_reconcile

_log = get_logger(__name__)


@shared_task(  # type: ignore[misc,untyped-decorator,unused-ignore]
    name="iam.reconcile_keycloak",
    bind=False,
    ignore_result=True,
)
def reconcile_keycloak() -> dict[str, int]:
    """Run one DB -> Keycloak reconcile pass synchronously."""
    summary = asyncio.run(run_keycloak_reconcile())
    _log.info("iam.reconcile_keycloak.summary", **summary)
    return summary
