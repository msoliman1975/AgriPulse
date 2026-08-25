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
    # Phenology auto-advance: per-tenant daily sweep that moves each
    # eligible block to its calendar/age-derived growth_stage (writes
    # GrowthStageLog source='derived'). Locked blocks are skipped; the
    # recommendation engine reads the resulting stage unchanged.
    "phenology.advance_growth_stages": {
        "task": "phenology.advance_growth_stages",
        "schedule": float(_settings.phenology_advance_seconds),
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
    # The same sweep for farms that fetch their whole boundary rather than
    # one AOI per block. It enqueues nothing until a farm sets
    # `fetch_farm_aoi`, so this is inert until someone opts a farm in — the
    # cutover stays a per-farm decision, not a deploy.
    "imagery.discover_active_farm_subscriptions": {
        "task": "imagery.discover_active_farm_subscriptions",
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
    # Weather-index climatology: weekly per-tenant sweep that refreshes
    # the farm-scoped `weather_index_baselines` from `weather_index_daily`
    # history and re-derives the z-score on existing rows (Weather-Indices
    # PR-W3). Light queue — pure aggregation math like the indices sweep.
    "weather.recompute_baselines_sweep": {
        "task": "weather.recompute_baselines_sweep",
        "schedule": float(_settings.weather_baseline_recompute_seconds),
        "options": {"queue": "light"},
    },
    # Materialize the index continuous aggregates. Their refresh policies
    # use rolling windows (3d daily / 21d weekly), so a historical backfill
    # writes rows outside them and they are never materialized — and since
    # the views are real-time aggregates, buckets older than the
    # materialization threshold come from the materialized store alone, so
    # that history is invisible to readers until an explicit refresh. Light
    # queue: a full refresh of both views measured ~2.5s per tenant.
    "indices.refresh_index_caggs_sweep": {
        "task": "indices.refresh_index_caggs_sweep",
        "schedule": float(_settings.indices_cagg_refresh_seconds),
        "options": {"queue": "light"},
    },
    # Daily disease/pest risk: walk active tenants and enqueue a per-tenant
    # `weather.compute_risk_for_tenant`, which scores each crop block against a
    # trailing weather window and upserts `weather_risk_daily` (Weather-Indices
    # PR-R2). Light queue — pure accumulation math.
    "weather.compute_risk_daily_sweep": {
        "task": "weather.compute_risk_daily_sweep",
        "schedule": float(_settings.weather_risk_compute_seconds),
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
    # Daily crop water balance per block: precip + irrigation - ETc, the
    # correction to finding D7 of the indices gap audit. Runs against
    # YESTERDAY rather than today — a balance needs a whole day of ET₀,
    # rainfall and irrigation to mean anything, and evaluated mid-morning it
    # would report every block in deficit simply because the day is young.
    # Idempotent on `(block_id, date)`, so the hourly cadence just keeps
    # yesterday's row current as late irrigation logs arrive.
    "irrigation.water_balance_sweep": {
        "task": "irrigation.water_balance_sweep",
        "schedule": float(_settings.irrigation_water_balance_sweep_seconds),
        "options": {"queue": "light"},
    },
    # SPI-90 per farm, scored against that farm's own rainfall history. Far
    # cheaper than it sounds — it reads the daily `rainfall` index rows rather
    # than years of hourly observations — but there is no reason to run it
    # more than daily: a 90-day accumulation barely moves in an hour, and
    # farms too arid to fit are skipped outright.
    "weather.compute_spi_sweep": {
        "task": "weather.compute_spi_sweep",
        "schedule": float(_settings.weather_spi_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Recommendations engine: walk every active block per tenant and
    # evaluate every active decision tree against the latest signals.
    # Hourly in every environment -- see the setting for why.
    # Idempotent on the partial UNIQUE `(block_id, tree_id) WHERE
    # state='open'` — re-running while a prior recommendation is still
    # open is a no-op.
    "recommendations.evaluate_sweep": {
        "task": "recommendations.evaluate_sweep",
        "schedule": float(_settings.recommendations_evaluate_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Retention for the evaluation lineage the sweep above writes (tenant
    # 0062). Deletes runs past the window; their traces follow via the
    # run_id cascade, so the window is expressed once on the parent. Light
    # queue — a plain indexed DELETE, unlike the grid cleanup which has to
    # dig through a compressed hypertable.
    "recommendations.prune_eval_runs": {
        "task": "recommendations.prune_eval_runs",
        "schedule": float(_settings.recommendations_eval_run_prune_seconds),
        "kwargs": {"retention_days": _settings.recommendations_eval_run_retention_days},
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
    # Step 2 of a rezone. The apply only opens the new geometry at `now`
    # and leaves the old one serving its own history; handing history over
    # can only happen once the backfill has actually recomputed it, and
    # nothing signals when that is — so it is polled. Without this
    # schedule a rezone stays in its two-geometry state forever: safe, but
    # never finished. Idempotent and cheap when there's nothing to settle.
    "grid.settle_rezones_sweep": {
        "task": "grid.settle_rezones_sweep",
        "schedule": float(_settings.grid_settle_rezones_sweep_seconds),
        "options": {"queue": "light"},
    },
    # Reclaim rows belonging to geometries that govern nothing. Runs on
    # `heavy` because deleting from a compressed hypertable is slow — the
    # reason this is out of band rather than inline with the apply.
    "grid.cleanup_superseded_grids": {
        "task": "grid.cleanup_superseded_grids",
        "schedule": float(_settings.grid_cleanup_superseded_seconds),
        "kwargs": {"retention_days": _settings.grid_superseded_retention_days},
        "options": {"queue": "heavy"},
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
    # Platform-wide alert sweep. Distinct from the streak watcher above,
    # which notifies *tenant* admins about recorded failures. This one
    # writes to `public.platform_alerts` for the platform operator, and
    # detects the failures that leave no failure row at all: a stream that
    # has gone quiet, a farm left behind by its own siblings, and a job
    # parked in `running` that will never finish or fail.
    "platform_alerts.sweep": {
        "task": "platform_alerts.sweep",
        "schedule": float(_settings.platform_alert_sweep_seconds),
        "options": {"queue": "light"},
    },
    # The recovery half of the `stuck_job` alert. A worker killed between
    # `mark_running` and the terminal write leaves a job row that nothing
    # else can reach, so the scene never lands for that block. This returns
    # those rows to `pending` and dispatches them again, up to a capped
    # number of attempts. Runs on `light`: it only writes status rows and
    # queues work, the acquisitions themselves go to `heavy`.
    "imagery.reap_stuck_jobs": {
        "task": "imagery.reap_stuck_jobs",
        "schedule": float(_settings.imagery_reap_stuck_jobs_seconds),
        "options": {"queue": "light"},
    },
    # Same idea for weather, which never had one. A stranded weather attempt
    # loses no data, but it is counted as `running` for ever and that is the
    # number the Integration Health page shows an operator.
    "weather.reap_stale_attempts": {
        "task": "weather.reap_stale_attempts",
        "schedule": float(_settings.weather_reap_stale_attempts_seconds),
        "options": {"queue": "light"},
    },
}
