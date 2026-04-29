"""Heavy-queue worker entrypoint.

Run:  celery -A workers.heavy.main worker --loglevel=INFO --queues=heavy --concurrency=2
"""

from __future__ import annotations

from app.shared.eventbus import get_default_bus
from workers.celery_factory import build_celery
from workers.tasks.eventbus_dispatch import celery_dispatcher

app = build_celery("heavy")

get_default_bus().set_dispatcher(celery_dispatcher)
