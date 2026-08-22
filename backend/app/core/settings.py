"""Application settings.

Loaded from environment variables (with .env support in dev). Single source
of truth â€” modules import `get_settings()` rather than reading os.environ.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level settings. Field names map to env vars (case-insensitive)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Service ----------------------------------------------------------
    app_env: Literal["dev", "staging", "production", "test"] = "dev"
    app_debug: bool = False
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_metrics_port: int = 9090
    service_name: str = "agripulse-api"

    # --- Database ---------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://agripulse:agripulse@localhost:5432/agripulse")
    )
    database_sync_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+psycopg://agripulse:agripulse@localhost:5432/agripulse")
    )
    # When set, gets merged into database_url + database_sync_url if those
    # DSNs have no password component. Lets k8s deployments keep the
    # secret out of the URL string (which leaks into logs and tracebacks)
    # and only join them at runtime. The CNPG-managed `agripulse-pg-app`
    # k8s Secret exposes the rotating password as DATABASE_PASSWORD.
    database_password: str = ""
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_echo: bool = False

    # --- Redis ------------------------------------------------------------
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # --- Keycloak ---------------------------------------------------------
    keycloak_issuer: str = "https://keycloak.dev.agripulse.local/realms/agripulse"
    keycloak_audience: str = "agripulse-api"
    keycloak_jwks_url: str = (
        "https://keycloak.dev.agripulse.local/realms/agripulse" "/protocol/openid-connect/certs"
    )
    keycloak_jwks_cache_ttl_seconds: int = 3600

    # Admin-API client used by tenancy for ensure_group / invite_user etc.
    # When `keycloak_provisioning_enabled=False` the tenancy module wires a
    # no-op client; tenant creation still succeeds (operator follows the
    # runbook for the kcadm.sh fallback). Production envs flip this on +
    # set the four credentials. Tests inject FakeKeycloakClient directly.
    keycloak_provisioning_enabled: bool = False

    # --- Feature flags ---------------------------------------------------
    # Gates the /v1/farms/{id}/config/subscriptions/* endpoints + the
    # Defaults tab in FarmDrawer. ON by default — farm-level templates
    # are the canonical config surface. Override per-env to `False`
    # only if you need to stage the backfill of existing per-block
    # subscriptions before exposing templates. Removed in PR-4.
    farm_config_template_enabled: bool = True
    # Whether a tenant purge may skip the 30-day grace window via `force`.
    # Defaults True, which is exactly today's behaviour — `force` has always
    # been available to anyone holding platform.manage_tenants. It is a setting
    # now so a real production deployment can turn the escape hatch off without
    # a code change; dev and staging need it, because a test tenant that cannot
    # be removed for 30 days is a test tenant that never gets removed.
    purge_allow_immediate: bool = True
    keycloak_base_url: str = "https://keycloak.dev.agripulse.local"
    keycloak_realm: str = "agripulse"
    keycloak_admin_client_id: str = "agripulse-tenancy"
    keycloak_admin_client_secret: str = ""
    keycloak_admin_request_timeout_seconds: float = 10.0
    # Action URL the user is redirected to when accepting the welcome
    # email (UPDATE_PASSWORD action). Empty string omits the param so KC
    # uses the realm default.
    keycloak_invite_redirect_url: str = ""
    # When False, the invite / welcome flow skips the SMTP-dependent
    # `execute-actions-email` step and instead sets a one-time temporary
    # password that is returned in the API response (the inviting admin
    # hands it off out of band). When True (default) we email the reset
    # link and only fall back to a temp password if the send fails. Set
    # False for environments with no SMTP configured so onboarding never
    # silently strands users without a credential.
    keycloak_smtp_enabled: bool = True

    # --- Platform-admin bootstrap (PR-Reorg6) -----------------------------
    # On cold start, if no PlatformAdmin exists in
    # `public.platform_role_assignments`, the lifespan creates one from
    # these env values. Idempotent â€” subsequent boots are no-ops once a
    # PlatformAdmin exists. Empty email skips the bootstrap entirely.
    platform_admin_email: str = ""
    platform_admin_full_name: str = "Platform Admin"

    # --- Observability ----------------------------------------------------
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "agripulse-api"
    otel_resource_attributes: str = "deployment.environment=dev"

    # --- Celery -----------------------------------------------------------
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Object storage (S3-compatible) ----------------------------------
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "agripulse"
    s3_secret_access_key: str = "agripulse-dev"
    s3_bucket_uploads: str = "agripulse-uploads"
    s3_path_style: bool = True
    s3_presign_expires_seconds: int = 900

    # --- Periodic jobs ---------------------------------------------------
    # Cross-schema FK consistency check for `public.farm_scopes` â†”
    # `tenant_<id>.farms`. Hourly is enough â€” orphans only happen when a
    # farm is hard-deleted, which is operationally rare.
    farm_scope_consistency_check_seconds: int = 3600

    # Phenology auto-advance sweep cadence. Daily is plenty — stage windows
    # are day-granular (calendar DOY / days-from-planting). Runs after the
    # weather-derive cadence so any future GDD-based stages see fresh data.
    phenology_advance_seconds: int = 86400

    # IH-6: cadence for the DB -> Keycloak reconciler that re-asserts each
    # user's enabled flag + tenant attributes from the DB (source of
    # truth). 15 min keeps the drift window at most one token-refresh
    # beyond the access-token lifespan.
    keycloak_reconcile_seconds: int = 900

    # Sweep cadence for the Beat task that walks active subscriptions and
    # enqueues `discover_scenes`. Production overrides via env. Hourly in
    # dev so a fresh subscription returns imagery within one Beat cycle.
    imagery_discover_active_subscriptions_seconds: int = 3600

    # --- Sentinel Hub ----------------------------------------------------
    # Empty-by-default so dev fails closed if no creds are wired:
    # SentinelHubProvider.__init__ raises SentinelHubNotConfiguredError
    # when client_id or client_secret is empty (PR-B). Local dev fills
    # these via infra/dev/.env (gitignored); cluster envs via the
    # ExternalSecret agripulse-sentinel-hub.
    sentinel_hub_client_id: str = ""
    sentinel_hub_client_secret: str = ""
    sentinel_hub_oauth_url: str = "https://services.sentinel-hub.com/oauth/token"
    sentinel_hub_catalog_url: str = "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search"
    sentinel_hub_process_url: str = "https://services.sentinel-hub.com/api/v1/process"

    # --- Microsoft Planetary Computer (Landsat C2 L2 thermal) ------------
    # Anonymous: the STAC search needs no auth at all, and the SAS token
    # endpoint issues a ~1h read token for the blob container without an
    # account. That's why there are no credential settings here — if PC
    # ever gates this, the same files are in AWS `s3://usgs-landsat/`
    # (requester-pays), which is a credentials change, not a rewrite.
    planetary_computer_stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    planetary_computer_sas_url: str = "https://planetarycomputer.microsoft.com/api/sas/v1/token"
    # Landsat C2 L2 is delivered on a 30 m grid (the thermal band is
    # 100 m native, resampled up by USGS). Keep the fetch on the native
    # grid — resampling to 10 m would fake precision we do not have.
    landsat_native_resolution_m: float = 30.0

    # --- Open-Meteo (weather provider) -----------------------------------
    # Free public endpoints; no auth required. Override via env if you
    # ever stand up the commercial / self-hosted variant.
    open_meteo_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_archive_url: str = "https://archive-api.open-meteo.com/v1/archive"

    # Default cadence applied when `weather_subscriptions.cadence_hours`
    # is NULL. 3h x 24h/day = 8 fetches/farm/day, comfortably under
    # Open-Meteo's free-tier 10k req/day cap even with hundreds of farms.
    weather_default_cadence_hours: int = 3

    # Hour counts the ingestion task asks the provider for per fetch.
    # 48h past covers two days of "observations" (Open-Meteo updates the
    # past hourly model output every cycle, so re-fetching past entries
    # corrects them); 120h forecast = 5 days, the agronomy sweet spot.
    weather_past_hours: int = 48
    weather_forecast_hours: int = 120

    # Sweep cadence for the Beat task that walks active subscriptions
    # and enqueues `weather.fetch_weather`. 15 min in dev so a fresh
    # subscription returns observations within one Beat cycle.
    weather_discover_active_subscriptions_seconds: int = 900

    # Cadence for `indices.recompute_baselines_sweep`. Weekly in
    # production; one hour in dev so a fresh tenant sees baselines
    # land within a Beat cycle of getting their first imagery scenes.
    indices_baseline_recompute_seconds: int = 3600

    # Cadence for `weather.recompute_baselines_sweep` — the farm-scoped
    # climatology baselines over `weather_index_daily` (Weather-Indices
    # PR-W3). Same rationale + default as the indices baseline sweep.
    weather_baseline_recompute_seconds: int = 3600

    # Cadence for `indices.refresh_index_caggs_sweep`. The daily/weekly
    # continuous aggregates have rolling refresh policies (3d / 21d), so a
    # historical backfill lands outside them and stays unmaterialized —
    # i.e. invisible to every reader. A full refresh measured ~2.5s per
    # tenant, so hourly is cheap and bounds "backfilled history is not
    # visible yet" to one cycle.
    indices_cagg_refresh_seconds: int = 3600

    # Cadence for `weather.compute_risk_daily_sweep` — the per-block disease/
    # pest risk scores over a trailing weather window (Weather-Indices PR-R2).
    # 86400 = once per day; pure accumulation math, light queue.
    weather_risk_compute_seconds: int = 86400

    # Cadence for `alerts.evaluate_alerts_sweep`. Nightly in production;
    # 30 minutes in dev so a freshly-ingested scene flips into alerts
    # within one Beat cycle.
    alerts_evaluate_sweep_seconds: int = 1800

    # Cadence for `irrigation.generate_sweep`. Once per day suffices
    # in production (recommendations target a calendar day); hourly in
    # dev for fast iteration. The partial UNIQUE on schedules keeps
    # re-runs within the same day from duplicating.
    irrigation_generate_sweep_seconds: int = 3600

    # Cadence for `irrigation.water_balance_sweep`. Targets YESTERDAY, so
    # the interval governs how quickly a late irrigation log is reflected
    # rather than how fresh the reading is. Hourly keeps that responsive;
    # the upsert is idempotent on `(block_id, date)`.
    irrigation_water_balance_sweep_seconds: int = 3600

    # Cadence for `weather.compute_spi_sweep`. Daily: a 90-day rainfall
    # accumulation does not move meaningfully within a day, and the task
    # rescores the previous day rather than a partial one.
    weather_spi_sweep_seconds: int = 86400

    # Cadence for `recommendations.evaluate_sweep`. Daily in production
    # â€” decision trees consume slow-moving signals (NDVI baselines).
    # Hourly in dev so a fresh aggregate triggers a recommendation
    # within one Beat cycle. Partial UNIQUE on (block_id, tree_id)
    # WHERE state='open' keeps re-runs idempotent.
    recommendations_evaluate_sweep_seconds: int = 3600

    # Cadence for `recommendations.prune_eval_runs`. Daily — the rows it
    # drops are already past the retention window below, so running it more
    # often only changes how promptly a day's worth of expiry is reclaimed.
    recommendations_eval_run_prune_seconds: int = 86400
    # How long decision-tree evaluation lineage is kept. Deleting a run
    # cascades to its traces (tenant migration 0062), so this one number
    # governs the whole table. 100 days spans a full season's worth of
    # "why did this fire back in March?" without letting ~5k rows/tenant/day
    # accumulate indefinitely.
    recommendations_eval_run_retention_days: int = 100

    # Per-cell grid observation retention (block_grid_aggregates). None =
    # compress-only, keep everything (the current deliberate policy — see
    # docs/proposals/grid-aggregates-retention.md). Set to a day count
    # (e.g. 730 for ~24 months) and run scripts/apply_grid_retention to
    # add a TimescaleDB retention policy that drops older chunks. Disabled
    # by default so no data is ever dropped without an explicit opt-in.
    grid_aggregates_retention_days: int | None = None

    # Cadence for `grid.detect_anomalies_sweep` — per-tenant spatial
    # anomaly detection over each active sub-block grid. Hourly by default
    # (same grain as the recommendations sweep); a fresh scene's per-cell
    # aggregates turn into a worst-cells alert within one Beat cycle.
    # Idempotent on the alerts partial UNIQUE (block_id, rule_code).
    grid_anomaly_detect_sweep_seconds: int = 3600

    # Cadence for `grid.settle_rezones_sweep` — step 2 of a rezone, which
    # hands history to the new geometry once the backfill has recomputed
    # it. Hourly: it is idempotent and cheap when there is nothing to
    # settle, and a rezone that finishes backfilling should not sit in a
    # two-geometry state for long.
    grid_settle_rezones_sweep_seconds: int = 3600

    # Cadence for `grid.cleanup_superseded_grids`. Daily — the rows it
    # drops are already governing nothing, and the retention delay below
    # is what actually decides when they go.
    grid_cleanup_superseded_seconds: int = 86400
    # How long a fully-replaced geometry's rows are kept. This is a
    # deliberate delay, not a performance knob: it keeps the previous
    # geometry recoverable after a rezone that turns out to be a mistake.
    grid_superseded_retention_days: int = 7

    # Cadence for `integrations_health.probe_providers` (PR-IH5). 5 min
    # is the proposal default for Open-Meteo; if Sentinel Hub probe
    # costs need throttling, raise it. Each probe is a single HTTP
    # round-trip per provider, so the cost grows linearly with the
    # provider catalog rather than tenant count.
    provider_probe_seconds: int = 300

    # PR-IH11. Beat cadence for the consecutive-failure-streak watcher.
    # 10 min strikes a balance: alerting within a beat or two of the
    # third failure (so a 15-min weather cadence with 3 fails crosses
    # the threshold within ~45 min) while keeping the sweep cheap.
    integration_failure_check_seconds: int = 600

    # Streak length that triggers a single inbox alert. Three is
    # conservative: a one-off network blip + a noisy retry both
    # naturally clear without paging anyone; sustained breakage
    # (3 strikes) is worth a notification. Per-tenant override via
    # `platform_defaults` is a future follow-up.
    integration_failure_streak_threshold: int = 3

    # --- Platform alert sweep (stop-gap operator observability) ----------
    # `platform_alerts.sweep` walks every active tenant and writes into
    # `public.platform_alerts`. 10 min matches the streak watcher: these
    # are hours-scale problems, so a tighter cadence buys nothing and the
    # sweep is linear in tenant count.
    platform_alert_sweep_seconds: int = 600

    # Staleness ceilings, in hours, per stream. A stream older than its
    # warning ceiling opens a `warning`; older than its critical ceiling
    # escalates the same row to `critical`.
    #
    # These are revisit-aware, not arbitrary. Weather polls on a 24h
    # cadence, so 26h is one missed poll plus slack. Sentinel-2 over a
    # single tile is covered by one relative orbit, which in the worst
    # case is a 5-day gap between usable passes -- 6 days is the first
    # age that cannot be explained by the satellite. Landsat 8 + 9
    # interleave to about 8 days over one path, so thermal needs roughly
    # double the optical ceiling before silence means anything.
    #
    # Set them lower and the page fills with alerts for farms that are
    # merely between passes, which is exactly how an alert list becomes
    # something operators stop reading.
    platform_alert_weather_warn_hours: int = 26
    platform_alert_weather_crit_hours: int = 50
    platform_alert_optical_warn_hours: int = 144
    platform_alert_optical_crit_hours: int = 240
    platform_alert_thermal_warn_hours: int = 288
    platform_alert_thermal_crit_hours: int = 480

    # Peer-lag detector. A farm is "behind its peers" when another farm in
    # the same tenant ingested a scene for the same product and this farm
    # still has not, this many hours later.
    #
    # 26h is deliberate. Discovery runs on a 24h cadence whose phase is
    # whatever time of day the subscription last ran, so two farms on the
    # same tile can legitimately sit up to a full day apart -- that is a
    # phase offset, not a fault. Anything past 26h is no longer explained
    # by the cadence.
    platform_alert_peer_lag_hours: int = 26

    # An imagery job still in a non-terminal state after this long has
    # stopped, not slowed. Production had one sitting in `running` for
    # eleven days; nothing flagged it, because a job that never finishes
    # also never fails.
    platform_alert_stuck_job_hours: int = 6

    # A `task_error` alert has no sweep to re-detect it -- it is written by
    # a Celery failure signal, so absence of news is the only recovery
    # signal available. Auto-resolve after this long with no new failure.
    # 6h spans several runs of every scheduled task we have.
    platform_alert_task_quiet_hours: int = 6

    # --- Platform alert email --------------------------------------------
    # Who gets the mail is a per-admin checkbox on
    # `public.platform_role_assignments.receives_alert_emails`, not a
    # setting. This switch exists so an environment can turn the whole
    # channel off without editing anyone's record - useful in dev, where
    # SMTP points at MailHog and the alert list is mostly noise.
    platform_alert_email_enabled: bool = True
    # One digest per sweep, capped. A tenant migration that breaks every
    # farm at once can produce hundreds of findings; a mail listing all of
    # them is unreadable and would very likely be rejected on size. The
    # ones past the cap are still marked as notified, and the mail says how
    # many were left out - repeating them in the next digest would mean a
    # mail every 10 minutes for as long as the problem lasted.
    platform_alert_email_max_items: int = 25

    # --- Imagery thresholds ----------------------------------------------
    # ARCHITECTURE.md Â§ 9: 60% for visualization, 20% for index aggregation.
    # Per-tenant overrides live on `imagery_aoi_subscriptions.cloud_cover_max_pct`
    # (NULL = use these defaults) â€” applied by service code in PR-B/PR-C.
    imagery_cloud_cover_visualization_max_pct: int = 60
    imagery_cloud_cover_aggregation_max_pct: int = 20
    # Discovery re-scans `[last_successful_ingest_at - lookback, now]` on every
    # poll. The watermark is wall-clock, but the catalogue `from` filter is
    # scene *sensing* time — a scene sensed before a poll but published to the
    # catalogue after it would otherwise fall behind the watermark and be
    # skipped forever. The lookback re-covers that publication-latency gap;
    # `upsert_pending_ingestion_job` is idempotent on (subscription_id,
    # scene_id), so the overlap costs one cheap catalogue search and no
    # re-acquisition. 48h comfortably covers a 24h cadence + L2A latency and
    # tolerates one missed poll.
    imagery_discovery_lookback_hours: int = 48

    # Hour of day (UTC) a daily subscription becomes due, on top of the plain
    # "last attempt older than cadence" rule.
    #
    # Without it, a 24h cadence is anchored wherever the previous attempt
    # happened to land and stays there. Measured on prod 2026-08-20: the
    # Agrosina farm subscription last polled at 03:23 UTC, while that day's
    # Sentinel-2 L2A scene was published at 12:30 UTC. The poll ran nine hours
    # before the scene existed, so the newest reading in the product was three
    # days old while a same-day scene sat in the catalogue.
    #
    # 14:00 UTC clears Sentinel-2's typical 3-6h L2A publication latency for
    # EMEA longitudes (sensing ~08:30 UTC over Egypt). It is a single global
    # hour, so a fleet spread over many longitudes wants either a later value
    # or a per-subscription column; set it to None to switch the rule off and
    # keep pure cadence behaviour.
    imagery_discovery_anchor_hour_utc: int | None = 14

    # Cold-start floor: how far back a *fresh* subscription's discovery reaches
    # when it has no `last_successful_ingest_at` watermark yet. Normal daily
    # discovery is watermark-driven, so this only bounds the very first poll.
    # The one-shot historical backfill task (`imagery.backfill_scenes`)
    # overrides the discovery window explicitly and ignores this floor.
    imagery_backfill_floor_days: int = 90

    # Native ground sample distance (metres) requested from the provider's
    # Process API per scene. The fetch payload previously omitted output
    # resolution, so Sentinel Hub defaulted to a fixed 256x256 grid — every
    # AOI was resampled regardless of true size, inflating pixel counts
    # 25-55x and biasing the mean on smaller / non-square blocks by up to
    # ~0.03 NDVI (see docs/reports/index-accuracy-agrosina-2026-06-20.md).
    # Pinning resx/resy to the product's native GSD makes aggregates match
    # the provider's own server-side computation. 10 m = Sentinel-2 L2A.
    imagery_native_resolution_m: float = 10.0

    # Apply the Sentinel-2 SCL scene-classification mask before aggregating:
    # cloud / shadow / cirrus / snow / saturated pixels become NaN, so they
    # drop out of `valid_pixel_count` and `valid_pixel_pct` reflects the real
    # clear-pixel fraction (the cloud-cover gate then has teeth). Requires the
    # provider to fetch one extra band (SCL) into the raw COG. Off → legacy
    # behaviour: no mask, every in-AOI pixel counts as valid. Raw COGs written
    # before this flag (no SCL band) are read unmasked regardless.
    imagery_cloud_mask_enabled: bool = True

    # --- Tile server -----------------------------------------------------
    # Served to the frontend via GET /api/v1/config in PR-C so the SPA
    # never hard-codes the URL. Local dev: TiTiler on host port 8001.
    tile_server_base_url: str = "http://localhost:8001"

    # --- SMTP (notifications email channel, PR-S4-D) ---------------------
    # Local dev: MailHog from infra/dev/compose.yaml on localhost:1025
    # (no auth, no TLS). Cluster envs override via ExternalSecret.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_from: str = "AgriPulse <noreply@agripulse.local>"
    smtp_timeout_seconds: float = 10.0

    # Origin the web app is served from. Notification links are built
    # relative (`/action-center/...`) because the in-app bell hands them
    # straight to react-router's `navigate()`, which treats an absolute
    # URL as a path and produces `/https://...`. An email has no origin to
    # resolve a relative path against, so the email channel prefixes this.
    # Trailing slashes are stripped when the link is built.
    app_base_url: str = "http://localhost:5173"

    # --- FCM (notifications push channel, scout app S2) ------------------
    # Off by default so a dev environment without Firebase credentials records
    # `skipped` dispatch rows rather than failing every send. Cluster envs
    # override via ExternalSecret.
    fcm_enabled: bool = False
    fcm_project_id: str = ""
    # Path to the Firebase service-account JSON. Preferred: the app mints and
    # refreshes its own bearer, because FCM v1 tokens expire after an hour.
    fcm_service_account_file: str = ""
    # The same credential inline, for deployments that inject secrets as env
    # vars rather than mounted files. Hetzner seeds plain Secrets consumed via
    # `envFrom` and the charts mount no secret volumes, so requiring a path
    # would mean adding a volume to every chart that sends push.
    fcm_service_account_json: str = ""
    # Escape hatch for a one-off manual test: a hand-minted bearer. Wins over
    # the service account when set, and stops working an hour later.
    fcm_access_token: str = ""
    fcm_timeout_seconds: float = 10.0

    # --- Webhook channel (PR-S4-E) ---------------------------------------
    # Per-tenant ``webhook_endpoint_url`` is the receiver URL; the HMAC
    # secret in production resolves through KMS (the per-tenant
    # ``webhook_signing_secret_kms_key`` row), but dev has no KMS â€” so
    # ``webhook_dev_secret`` is the fallback when no KMS key is wired.
    # Empty string disables the dev fallback (failed signature).
    webhook_dev_secret: str = "dev-only-not-for-prod"
    webhook_timeout_seconds: float = 5.0

    # --- Notification sink (simulation harness) ---------------------------
    # Tenants whose slug starts with this prefix have every outbound
    # notification suppressed: email, push and webhook are recorded as
    # dispatched-but-suppressed and nothing leaves the system. The simulation
    # harness runs a throwaway tenant on production beside real customers, so
    # this must stay per-tenant — a process-wide switch would silence theirs.
    # Empty (the default) disables suppression entirely, which is correct for
    # every environment that does not host simulation runs.
    notification_sink_tenant_prefix: str = ""

    # --- CORS -------------------------------------------------------------
    cors_allowed_origins: list[str] = Field(default_factory=list)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> list[str] | object:
        """Allow CORS_ALLOWED_ORIGINS to be passed as a comma-separated string."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _inject_database_password(self) -> Settings:
        """Splice `database_password` into the DSNs if they carry no
        password of their own. Lets k8s deployments keep the secret out
        of the URL env var (URLs leak into logs and tracebacks).
        Operates on the URL string because PostgresDsn is a multi-host
        URL in pydantic v2 and `.password` lives per-host, not top-level.
        """
        if not self.database_password:
            return self
        from urllib.parse import quote

        pw = quote(self.database_password, safe="")
        for attr in ("database_url", "database_sync_url"):
            raw = str(getattr(self, attr))
            scheme, _, rest = raw.partition("://")
            if not rest:
                continue
            authority, slash, path = rest.partition("/")
            # `user@host` => splice password as `user:pw@host`. Skip if
            # an `:password@` is already present so explicit URLs win.
            userinfo, at, hostport = authority.partition("@")
            if not at or ":" in userinfo:
                continue
            new_url = f"{scheme}://{userinfo}:{pw}@{hostport}"
            if slash:
                new_url += "/" + path
            object.__setattr__(self, attr, PostgresDsn(new_url))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    The lru_cache means env-var changes mid-process require a manual
    `get_settings.cache_clear()` â€” used in tests.
    """
    return Settings()
