"""Insights API schemas. Shaped for the Farm health overview FE."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.shared.health import Health

# Granularity is a closed set tied to the indices CAGG mapping
# (`block_index_daily` / `block_index_weekly`). The insights endpoint
# accepts the same vocabulary so the FE can swap without translation.
TimeseriesGranularity = Literal["daily", "weekly"]


class FarmIndexTimeseriesPoint(BaseModel):
    """One bucket × block in the per-block farm timeseries.

    `value` is the bucket mean; null buckets are dropped server-side
    so the FE never has to filter. Each Point carries `block_id` +
    `block_name` so the chart can render N labelled series from one
    flat array.
    """

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    block_id: UUID
    block_name: str
    value: Decimal | None


class FarmIndexTimeseriesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    index_code: str
    granularity: TimeseriesGranularity
    points: list[FarmIndexTimeseriesPoint]


class BlockHealthRow(BaseModel):
    """One scorecard row per block.

    `trend_30d_pct` is the percentage change from the value at (now -
    30d) to the current value, computed on the daily CAGG. `null`
    when there's no value at one or both endpoints.

    `last_observation_at` is the timestamp of the most recent index
    observation regardless of value column — lets the FE render "2
    days ago" so the operator knows freshness.
    """

    model_config = ConfigDict(from_attributes=True)

    block_id: UUID
    block_name: str
    current_health: Health
    current_value: Decimal | None
    trend_30d_pct: Decimal | None
    alerts_open: int
    last_observation_at: datetime | None


class FarmHealthSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    # The index used to compute `current_value` and `trend_30d_pct`.
    # Always NDVI in V1; exposed so a future overlay can swap it.
    index_code: str
    blocks: list[BlockHealthRow]
