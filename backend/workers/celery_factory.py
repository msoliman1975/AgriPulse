"""Celery app factory shared by the three task-worker entrypoints.

Each entrypoint picks a queue and calls `build_celery("light"|"heavy"|"beat")`.
The returned `Celery` instance is what the `celery` CLI binds to.

Terminology: a "task worker" here is a background-job process consuming a
Celery queue. It is unrelated to the in-app "Worker" domain concept (farm
personnel in `app.modules.resources`, surfaced under Settings ▸ Workers).
Keep the two senses distinct in code and docs — say "task worker / queue"
for this tier.
"""

from __future__ import annotations

from typing import Literal

from celery import Celery

from app.core.logging import configure_logging
from app.core.settings import get_settings

QueueName = Literal["light", "heavy", "beat"]

_TASK_PACKAGES: tuple[str, ...] = (
    "workers.tasks",
    # `app.modules.recommendations` was named as the package for its whole
    # life, and its `__init__.py` is a docstring, so `tasks.py` was never
    # imported, the three @shared_task decorators never ran, and
    # `recommendations.evaluate_sweep` was unregistered on every worker.
    # Beat dispatched it hourly and the light worker answered "Received
    # unregistered task ... KeyError" every time, which is a log line and
    # not an alert. Net effect: the sweep has never evaluated a decision
    # tree in production. `evaluate_for_tenant` and `prune_eval_runs` were
    # dead the same way. The rule stated in the comment below was already
    # written; these three entries predate it.
    #
    # `audit` and `notifications` stay as packages on purpose: neither owns
    # a tasks module, so there is nothing for a `.tasks` suffix to name.
    "app.modules.audit",
    "app.modules.notifications",
    "app.modules.recommendations.tasks",
    # Celery's `include=` imports the literal module name â€” packages are
    # NOT recursed. Point at the submodule that owns the @shared_task
    # decorators so Beat-dispatched tasks resolve on workers.
    "app.modules.imagery.tasks",
    "app.modules.indices.tasks",
    # Observer verification runs (heavy queue: `full` mode reads every band).
    "app.modules.observer.tasks",
    "app.modules.weather.tasks",
    "app.modules.farms.tasks",
    # Phenology auto-advance sweep (writes growth_stage source='derived').
    "app.modules.farms.phenology_tasks",
    # IH-6: periodic DB -> Keycloak reconciler.
    "app.modules.iam.tasks",
    # Stage 2 of the rules sunset deleted `alerts.tasks`. Trees own
    # alert generation now via `recommendations.tasks`. The Beat
    # config in `workers/beat/main.py` no longer schedules an alerts
    # sweep either.
    "app.modules.irrigation.tasks",
    "app.modules.integrations_health.probes",
    "app.modules.integrations_health.streak_watcher",
    # Platform alert sweep. Importing this module on every worker is what
    # registers the `task_failure` signal handler, so a task that dies
    # before writing anything still leaves a trace.
    "app.modules.platform_alerts.tasks",
    # Sub-block grid spatial-anomaly alerting sweep.
    "app.modules.grid.tasks",
    # Platform-admin hard delete. Only large purges reach a worker; small
    # ones run inline in the request.
    "app.modules.purge.tasks",
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
        f"agripulse-{queue}",
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


def build_publisher() -> Celery:
    """Construct a publisher-side Celery app for the FastAPI process.

    Without this, `@shared_task` decorators resolve to Celery's implicit
    default app â€” which has no broker configured and silently falls
    through to amqp://localhost:5672. Calls to `task.delay(...)` from
    the API process then 500 with `kombu.exceptions.OperationalError:
    Connection refused`.

    Constructing a Celery instance has the side effect of becoming
    `current_app`, which is what `@shared_task` resolves through. The
    queue name we pass is the publisher-side default â€” task fan-out
    relies on `task_routes` (not configured yet) for per-task targeting.
    """
    return build_celery("light")
