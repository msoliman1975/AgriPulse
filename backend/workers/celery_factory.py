"""Celery app factory shared by the three worker entrypoints.

Each entrypoint picks a queue and calls `build_celery("light"|"heavy"|"beat")`.
The returned `Celery` instance is what the `celery` CLI binds to.
"""

from __future__ import annotations

from typing import Literal

from celery import Celery

from app.core.logging import configure_logging
from app.core.settings import get_settings

QueueName = Literal["light", "heavy", "beat"]

_TASK_PACKAGES: tuple[str, ...] = (
    "workers.tasks",
    "app.modules.audit",
    "app.modules.notifications",
    "app.modules.alerts",
    "app.modules.recommendations",
    "app.modules.indices",
    "app.modules.imagery",
)


def build_celery(queue: QueueName) -> Celery:
    """Construct a Celery app bound to a single queue.

    The same broker URL is used for every queue; routing is by task name
    via `task_routes`. A worker started against this Celery instance
    consumes only its own queue.
    """
    configure_logging()
    settings = get_settings()

    app = Celery(
        f"missionagre-{queue}",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=list(_TASK_PACKAGES),
    )

    app.conf.update(
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_reject_on_worker_lost=True,
        task_default_queue=queue,
        task_routes={
            # Wire-up of per-task routing happens as modules are built.
            # Until then everything published goes to the default queue
            # of the worker that publishes it.
        },
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
    )
    return app
