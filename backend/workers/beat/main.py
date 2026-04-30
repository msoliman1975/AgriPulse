"""Beat scheduler entrypoint.

Run:  celery -A workers.beat.main beat --loglevel=INFO

Schedules live here so they're discoverable in one file. Cadence values
that matter operationally are sourced from settings, so dev clusters
can run faster than production without touching code.
"""

from __future__ import annotations

from app.core.settings import get_settings
from workers.celery_factory import build_celery

app = build_celery("beat")

_settings = get_settings()

app.conf.beat_schedule = {
    "farms.farm_scope_consistency_check": {
        "task": "farms.farm_scope_consistency_check",
        "schedule": float(_settings.farm_scope_consistency_check_seconds),
        "options": {"queue": "light"},
    },
}
