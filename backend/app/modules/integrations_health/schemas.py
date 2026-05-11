"""Integration health response schemas — read-only views of weather/imagery
sync state per Farm and per Block.

The view bodies live in tenant migrations 0019 + 0022; these schemas
mirror the shape and are used by both the routers and the queries hook
on the frontend (via OpenAPI/typed clients later)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FarmIntegrationHealthResponse(BaseModel):
    """One row from `tenant_<id>.v_farm_integration_health`."""

    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    farm_name: str
    weather_active_subs: int
    weather_last_sync_at: datetime | None
    weather_last_failed_at: datetime | None
    imagery_active_subs: int
    imagery_last_sync_at: datetime | None
    imagery_failed_24h: int
    # PR-IH2 additions
    weather_failed_24h: int = 0
    weather_running_count: int = 0
    imagery_running_count: int = 0
    weather_overdue_count: int = 0
    imagery_overdue_count: int = 0


class BlockIntegrationHealthResponse(BaseModel):
    """One row from `tenant_<id>.v_block_integration_health`."""

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    farm_id: UUID
    block_name: str
    weather_active_subs: int
    weather_last_sync_at: datetime | None
    weather_last_failed_at: datetime | None
    imagery_active_subs: int
    imagery_last_sync_at: datetime | None
    imagery_failed_24h: int
    # PR-IH2 additions
    weather_failed_24h: int = 0
    weather_running_count: int = 0
    imagery_running_count: int = 0
    weather_overdue_count: int = 0
    imagery_overdue_count: int = 0


class IntegrationAttemptRow(BaseModel):
    """One row from `tenant_<id>.v_integration_recent_attempts`.

    Unified shape across weather + imagery. `scene_id` is imagery-only;
    `rows_ingested` is weather-only. Both are nullable.
    """

    model_config = ConfigDict(from_attributes=True)

    attempt_id: UUID
    kind: str  # 'weather' | 'imagery'
    subscription_id: UUID
    block_id: UUID
    farm_id: UUID | None
    provider_code: str | None
    started_at: datetime
    completed_at: datetime | None
    status: str  # 'running' | 'succeeded' | 'failed' | 'skipped'
    duration_ms: int | None
    rows_ingested: int | None
    error_code: str | None
    error_message: str | None
    scene_id: str | None
