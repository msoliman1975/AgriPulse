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
    # IH-6: DB -> Keycloak reconciler. Re-asserts each provisioned user's
    # enabled flag + tenant_id/tenant_role attributes from the DB so a
    # role flipped in the DB, a suspended membership, or a soft-deleted
    # user converges in Keycloak within one cycle (gaps G6, G11).
    "iam.reconcile_keycloak": {
        "task": "iam.reconcile_keycloak",
        "schedule": float(_settings.keycloak_reconcile_seconds),
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
    # PR-F (sunset rules engine): the rules-based alerts sweep is
    # disabled. Alerts now flow from decision-tree leaves with
    # `kind: alert` via the recommendations engine sweep below; the
    # ndvi_baseline_alert_v1 seed tree replaces the platform
    # default_rules entries 1:1. The alerts table, repository, and
    # service stay live (trees write into them via
    # `_open_alert_from_tree` in PR-E), and `alerts/engine.py` +
    # `alerts/tasks.py` remain importable so existing integration
    # tests keep exercising the legacy code path until follow-up
    # tickets retire them. To re-enable temporarily for parity
    # debugging, re-add the entry below and bump
    # `alerts_evaluate_sweep_seconds`.
    #
    # "alerts.evaluate_alerts_sweep": {
    #     "task": "alerts.evaluate_alerts_sweep",
    #     "schedule": float(_settings.alerts_evaluate_sweep_seconds),
    #     "options": {"queue": "light"},
    # },
    # Irrigation engine: per-block daily recommendations from ET₀ +
    # crop Kc + recent precip. Idempotent on the partial UNIQUE
    # `(block_id, scheduled_for) WHERE status='pending'` so re-runs
    # within the same calendar day don't spawn duplicates.
    "irrigation.generate_sweep": {
        "task": "irrigation.generate_sweep",
        "schedule": float(_settings.irrigation_generate_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Recommendations engine: walk every active block per tenant and
    # evaluate every active decision tree against the latest signals.
    # Idempotent on the partial UNIQUE `(block_id, tree_id) WHERE
    # state='open'` — re-running while a prior recommendation is still
    # open is a no-op.
    "recommendations.evaluate_sweep": {
        "task": "recommendations.evaluate_sweep",
        "schedule": float(_settings.recommendations_evaluate_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Sub-block grid spatial-anomaly alerting: per tenant, scan each
    # active grid's latest scene for cells doing markedly worse than the
    # field average and open a block-level alert naming the worst cells.
    # Idempotent on the alerts partial UNIQUE (block_id, rule_code).
    "grid.detect_anomalies_sweep": {
        "task": "grid.detect_anomalies_sweep",
        "schedule": float(_settings.grid_anomaly_detect_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Provider liveness probes (PR-IH5). Pings each active weather +
    # imagery provider on a tight cadence so the Providers tab can show
    # red/green status without waiting for a real tenant fetch to fail.
    # Probes run on `light` because they're seconds-long HTTP calls.
    "integrations_health.probe_providers": {
        "task": "integrations_health.probe_providers",
        "schedule": float(_settings.provider_probe_seconds),
        "options": {"queue": "light"},
    },
    # Consecutive-failure streak alerter (PR-IH11). Scans every active
    # tenant; for each subscription whose newest attempt is the Nth
    # consecutive failure (N = streak threshold) and which hasn't yet
    # been alerted on this streak, fans out an in-app inbox item to
    # every TenantOwner / TenantAdmin in that tenant.
    "integrations_health.check_failure_streaks": {
        "task": "integrations_health.check_failure_streaks",
        "schedule": float(_settings.integration_failure_check_seconds),
        "options": {"queue": "light"},
    },
}
