"""Pydantic schemas for the integrations config REST surface.

The same response shape works for tenant-, Farm-, and LandUnit-tier
reads: every endpoint returns a `ResolvedIntegrationSetting` block per
key showing the resolved value plus where it came from.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["platform", "tenant", "farm", "resource"]


class ResolvedIntegrationSetting(BaseModel):
    """One resolved key. The UI uses `source` to render the inheritance pill."""

    key: str
    value: Any
    source: Source
    overridden_at: datetime | None = None


# ---- Tenant tier --------------------------------------------------------


class TenantIntegrationSettingsResponse(BaseModel):
    """All resolved keys for one integration category, scoped to tenant."""

    settings: list[ResolvedIntegrationSetting]


class TenantSettingUpsertRequest(BaseModel):
    """PUT body — replace one tenant-level value."""

    model_config = ConfigDict(extra="forbid")
    value: Any = Field(description="Pre-validated by the resolver layer.")


# ---- Farm + LandUnit tiers ---------------------------------------------


class FarmWeatherOverridePayload(BaseModel):
    """PUT /integrations/weather/farms/{farm_id} body.

    NULL on a column = inherit from the next tier."""

    model_config = ConfigDict(extra="forbid")
    provider_code: str | None = None
    cadence_hours: int | None = Field(default=None, ge=1, le=24 * 7)


class FarmImageryOverridePayload(BaseModel):
    """PUT /integrations/imagery/farms/{farm_id} body."""

    model_config = ConfigDict(extra="forbid")
    product_code: str | None = None
    cloud_cover_threshold_pct: int | None = Field(default=None, ge=0, le=100)


class BlockImageryOverridePayload(BaseModel):
    """PUT /integrations/imagery/blocks/{block_id} body.

    Updates the per-block imagery_aoi_subscriptions row. cloud_cover
    here writes into `imagery_aoi_subscriptions.cloud_cover_max_pct`
    (the existing column)."""

    model_config = ConfigDict(extra="forbid")
    cloud_cover_max_pct: int | None = Field(default=None, ge=0, le=100)


class ApplyToBlocksRequest(BaseModel):
    """POST /integrations/imagery/farms/{farm_id}:apply-to-blocks body.

    Two modes:
      - "inherit": delete every per-block override under this Farm so
        they inherit from the Farm/tenant/platform tiers.
      - "lock":   write Farm's resolved values into every block as an
        explicit override row.
    """

    model_config = ConfigDict(extra="forbid")
    mode: Literal["inherit", "lock"]


class FarmOverrideResponse(BaseModel):
    """Farm-tier resolved settings + raw override row (NULLs visible)."""

    farm_id: UUID
    settings: list[ResolvedIntegrationSetting]
