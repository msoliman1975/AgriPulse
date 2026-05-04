"""Pydantic schemas for the indices module's REST surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Granularity matches the two continuous aggregates in
# `tenant_<id>.block_index_daily` / `block_index_weekly`. The trend chart
# in PR-D switches between them via this query-param value.
TimeseriesGranularity = Literal["daily", "weekly"]


class IndexCatalogEntry(BaseModel):
    """One row of `public.indices_catalog`. Surfaced under /api/v1/config."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name_en: str
    name_ar: str | None
    formula_text: str
    value_min: Decimal
    value_max: Decimal
    physical_meaning: str | None
    is_standard: bool


class IndexTimeseriesPoint(BaseModel):
    """One bucketed sample on the trend chart."""

    time: datetime = Field(description="Bucket start, RFC 3339.")
    mean: Decimal | None
    min: Decimal | None = None
    max: Decimal | None = None
    valid_pixels: int | None = None
    # Decimal in 0..100. NULL when the bucket aggregated zero rows.
    valid_pixel_pct: Decimal | None = None


class IndexTimeseriesResponse(BaseModel):
    """GET /api/v1/blocks/{block_id}/indices/{index_code}/timeseries body."""

    block_id: UUID
    index_code: str
    granularity: TimeseriesGranularity
    points: tuple[IndexTimeseriesPoint, ...]
