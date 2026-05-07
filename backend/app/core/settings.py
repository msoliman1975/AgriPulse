"""Application settings.

Loaded from environment variables (with .env support in dev). Single source
of truth — modules import `get_settings()` rather than reading os.environ.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
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
    service_name: str = "missionagre-api"

    # --- Database ---------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+asyncpg://missionagre:missionagre@localhost:5432/missionagre"
        )
    )
    database_sync_url: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+psycopg://missionagre:missionagre@localhost:5432/missionagre"
        )
    )
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_echo: bool = False

    # --- Redis ------------------------------------------------------------
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # --- Keycloak ---------------------------------------------------------
    keycloak_issuer: str = "https://keycloak.dev.missionagre.local/realms/missionagre"
    keycloak_audience: str = "missionagre-api"
    keycloak_jwks_url: str = (
        "https://keycloak.dev.missionagre.local/realms/missionagre" "/protocol/openid-connect/certs"
    )
    keycloak_jwks_cache_ttl_seconds: int = 3600

    # --- Observability ----------------------------------------------------
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str = "missionagre-api"
    otel_resource_attributes: str = "deployment.environment=dev"

    # --- Celery -----------------------------------------------------------
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Object storage (S3-compatible) ----------------------------------
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "missionagre"
    s3_secret_access_key: str = "missionagre-dev"
    s3_bucket_uploads: str = "missionagre-uploads"
    s3_path_style: bool = True
    s3_presign_expires_seconds: int = 900

    # --- Periodic jobs ---------------------------------------------------
    # Cross-schema FK consistency check for `public.farm_scopes` ↔
    # `tenant_<id>.farms`. Hourly is enough — orphans only happen when a
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
    # ExternalSecret missionagre-sentinel-hub.
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

    # --- Imagery thresholds ----------------------------------------------
    # ARCHITECTURE.md § 9: 60% for visualization, 20% for index aggregation.
    # Per-tenant overrides live on `imagery_aoi_subscriptions.cloud_cover_max_pct`
    # (NULL = use these defaults) — applied by service code in PR-B/PR-C.
    imagery_cloud_cover_visualization_max_pct: int = 60
    imagery_cloud_cover_aggregation_max_pct: int = 20

    # --- Tile server -----------------------------------------------------
    # Served to the frontend via GET /api/v1/config in PR-C so the SPA
    # never hard-codes the URL. Local dev: TiTiler on host port 8001.
    tile_server_base_url: str = "http://localhost:8001"

    # --- CORS -------------------------------------------------------------
    cors_allowed_origins: list[str] = Field(default_factory=list)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> list[str] | object:
        """Allow CORS_ALLOWED_ORIGINS to be passed as a comma-separated string."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance.

    The lru_cache means env-var changes mid-process require a manual
    `get_settings.cache_clear()` — used in tests.
    """
    return Settings()
