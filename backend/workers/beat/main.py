"""Beat scheduler entrypoint.

Run:  celery -A workers.beat.main beat --loglevel=INFO

The schedule itself is empty for now. Future prompts wire periodic
tasks (alert evaluation every 15 min, recommendation evaluation
daily, imagery polling at provider cadence) by adding entries to
`app.conf.beat_schedule`.
"""

from __future__ import annotations

from workers.celery_factory import build_celery

app = build_celery("beat")

app.conf.beat_schedule = {
    # No schedules yet. Each domain module that needs periodic work
    # contributes its own entry from its `service.py` startup hook
    # (added in subsequent prompts).
}
