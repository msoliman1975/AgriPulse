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
