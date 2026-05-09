"""Integration health response schemas — read-only views of weather/imagery
sync state per Farm and per Block.

The view bodies live in tenant migration 0019; these schemas mirror
the shape and are used by both the routers and the queries hook on the
frontend (via OpenAPI/typed clients later)."""

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
