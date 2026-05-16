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
    keycloak_base_url: str = "https://keycloak.dev.agripulse.local"
    keycloak_realm: str = "agripulse"
    keycloak_admin_client_id: str = "agripulse-tenancy"
    keycloak_admin_client_secret: str = ""
    keycloak_admin_request_timeout_seconds: float = 10.0
    # Action URL the user is redirected to when accepting the welcome
    # email (UPDATE_PASSWORD action). Empty string omits the param so KC
    # uses the realm default.
    keycloak_invite_redirect_url: str = ""

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

    # Cadence for `alerts.evaluate_alerts_sweep`. Nightly in production;
    # 30 minutes in dev so a freshly-ingested scene flips into alerts
    # within one Beat cycle.
    alerts_evaluate_sweep_seconds: int = 1800

    # Cadence for `irrigation.generate_sweep`. Once per day suffices
    # in production (recommendations target a calendar day); hourly in
    # dev for fast iteration. The partial UNIQUE on schedules keeps
    # re-runs within the same day from duplicating.
    irrigation_generate_sweep_seconds: int = 3600

    # Cadence for `recommendations.evaluate_sweep`. Daily in production
    # â€” decision trees consume slow-moving signals (NDVI baselines).
    # Hourly in dev so a fresh aggregate triggers a recommendation
    # within one Beat cycle. Partial UNIQUE on (block_id, tree_id)
    # WHERE state='open' keeps re-runs idempotent.
    recommendations_evaluate_sweep_seconds: int = 3600

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

    # --- Imagery thresholds ----------------------------------------------
    # ARCHITECTURE.md Â§ 9: 60% for visualization, 20% for index aggregation.
    # Per-tenant overrides live on `imagery_aoi_subscriptions.cloud_cover_max_pct`
    # (NULL = use these defaults) â€” applied by service code in PR-B/PR-C.
    imagery_cloud_cover_visualization_max_pct: int = 60
    imagery_cloud_cover_aggregation_max_pct: int = 20

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

    # --- Webhook channel (PR-S4-E) ---------------------------------------
    # Per-tenant ``webhook_endpoint_url`` is the receiver URL; the HMAC
    # secret in production resolves through KMS (the per-tenant
    # ``webhook_signing_secret_kms_key`` row), but dev has no KMS â€” so
    # ``webhook_dev_secret`` is the fallback when no KMS key is wired.
    # Empty string disables the dev fallback (failed signature).
    webhook_dev_secret: str = "dev-only-not-for-prod"
    webhook_timeout_seconds: float = 5.0

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
    def _inject_database_password(self) -> "Settings":
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
