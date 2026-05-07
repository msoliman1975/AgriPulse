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
    # Sweep every active subscription whose last attempt is older than
    # its cadence and enqueue `imagery.discover_scenes`. The actual
    # SH calls + acquisitions happen on the heavy worker queue; this
    # task just walks the catalog.
    "imagery.discover_active_subscriptions": {
        "task": "imagery.discover_active_subscriptions",
        "schedule": float(_settings.imagery_discover_active_subscriptions_seconds),
        "options": {"queue": "light"},
    },
    # Weather sweep: enqueue `weather.fetch_weather` for every (farm,
    # provider) pair whose oldest active subscription is overdue. The
    # sweep picks up new subscriptions within one Beat cycle.
    "weather.discover_due_subscriptions": {
        "task": "weather.discover_due_subscriptions",
        "schedule": float(_settings.weather_discover_active_subscriptions_seconds),
        "options": {"queue": "light"},
    },
    # Index baseline recompute: weekly per-tenant sweep that refreshes
    # `block_index_baselines` from the rolling history. Cheap math, so
    # daily would also be fine — weekly matches the data_model § 7
    # operator expectation and keeps Beat noise low.
    "indices.recompute_baselines_sweep": {
        "task": "indices.recompute_baselines_sweep",
        "schedule": float(_settings.indices_baseline_recompute_seconds),
        "options": {"queue": "light"},
    },
    # Alerts engine: walk every active block in every active tenant and
    # evaluate the rule catalog against the latest signals. Insertion is
    # idempotent (partial UNIQUE on (block_id, rule_code) WHERE
    # status IN open/ack/snoozed), so re-running is cheap.
    "alerts.evaluate_alerts_sweep": {
        "task": "alerts.evaluate_alerts_sweep",
        "schedule": float(_settings.alerts_evaluate_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Irrigation engine: per-block daily recommendations from ET₀ +
    # crop Kc + recent precip. Idempotent on the partial UNIQUE
    # `(block_id, scheduled_for) WHERE status='pending'` so re-runs
    # within the same calendar day don't spawn duplicates.
    "irrigation.generate_sweep": {
        "task": "irrigation.generate_sweep",
        "schedule": float(_settings.irrigation_generate_sweep_seconds),
        "options": {"queue": "light"},
    },
}
