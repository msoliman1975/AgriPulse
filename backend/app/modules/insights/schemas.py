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
    """One bucket x block in the per-block farm timeseries.

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


# ---- B.3: annotations + season + sparklines --------------------------------


# Kinds the FE knows how to render. `alert_opened` is amber for
# warning + red for critical; resolution events aren't surfaced
# (would clutter the chart and rarely change a decision).
AnnotationKind = Literal["alert_opened"]


class TimeseriesAnnotation(BaseModel):
    """One vertical marker on the FarmTrendChart. The FE drops a
    `<ReferenceLine x={time} stroke={color}>` for each, with a
    tooltip showing `label`."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    kind: AnnotationKind
    label: str
    # Maps to the FE's HEALTH_CHIP palette (red/amber/grey/slate).
    severity: Literal["critical", "warning", "info"] | None = None
    # Optional block focus — the FE may filter annotations down to
    # the currently-hovered block.
    block_id: UUID | None = None


class FarmAnnotationsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    annotations: list[TimeseriesAnnotation]


class SeasonContextCrop(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    crop_id: UUID
    name_en: str
    name_ar: str | None = None
    # How many blocks on this farm are planted with this crop. Used
    # by the FE to order the bar (most-planted first) and surface
    # mixed-crop farms.
    block_count: int


class FarmSeasonContextResponse(BaseModel):
    """Compact 'what's on this farm' header. Lighter than a real
    season-tracker (would need planting + expected-harvest dates per
    block); enough to give the operator a sense of crop mix when
    they land on the Insights page."""

    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    crops: list[SeasonContextCrop]
    # Total active blocks — handy when crops list is empty (no
    # BlockCrop rows seeded yet) so the FE can say "5 blocks, no
    # crops assigned" instead of an empty bar.
    active_block_count: int


class AlertTrendPoint(BaseModel):
    """One daily bucket in the alerts sparkline. `open_count` is the
    snapshot at end-of-day (cumulative opened minus resolved through
    that day, not including resolved-same-day)."""

    model_config = ConfigDict(from_attributes=True)

    date: datetime
    open_count: int


class FarmAlertTrendResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: UUID
    days: int
    points: list[AlertTrendPoint]
