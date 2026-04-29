"""Light-queue worker entrypoint.

Run:  celery -A workers.light.main worker --loglevel=INFO --queues=light
"""

from __future__ import annotations

from app.shared.eventbus import get_default_bus
from workers.celery_factory import build_celery
from workers.tasks.eventbus_dispatch import celery_dispatcher

app = build_celery("light")

# Wire async event handlers to dispatch through the worker's broker.
get_default_bus().set_dispatcher(celery_dispatcher)
