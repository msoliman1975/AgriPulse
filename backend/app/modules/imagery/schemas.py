"""Pydantic schemas for the imagery module's REST surface.

Wire format follows the conventions in ARCHITECTURE.md § 8: snake_case
JSON keys, RFC 3339 timestamps, m² for areas, cursor-based pagination.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Allowed values for imagery_ingestion_jobs.status — kept here so the
# router and tests share one source of truth.
IngestionJobStatus = Literal[
    "pending",
    "running",
    "succeeded",
    "failed",
    "skipped_cloud",
    "skipped_duplicate",
]

SceneSkippedReason = Literal["cloud", "duplicate", "out_of_window"]


# --- Subscriptions ----------------------------------------------------------


class SubscriptionCreate(BaseModel):
    """POST /api/v1/blocks/{block_id}/imagery/subscriptions body."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    cadence_hours: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Override per-tenant default. NULL = use the tenant default "
            "configured under tenant_settings."
        ),
    )
    cloud_cover_max_pct: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description=(
            "Override per-tenant default for the visualization threshold. "
            "NULL = use imagery_cloud_cover_visualization_max_pct."
        ),
    )


class SubscriptionRead(BaseModel):
    """GET /api/v1/blocks/{block_id}/imagery/subscriptions list item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    product_id: UUID
    cadence_hours: int | None
    cloud_cover_max_pct: int | None
    is_active: bool
    last_successful_ingest_at: datetime | None
    last_attempted_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --- Ingestion / scenes -----------------------------------------------------


class IngestionJobRead(BaseModel):
    """GET /api/v1/blocks/{block_id}/scenes list item.

    Asset URLs are TiTiler tile-URL templates; the frontend interpolates
    `{z}/{x}/{y}` per its own rendering needs.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    subscription_id: UUID
    product_id: UUID
    scene_id: str
    scene_datetime: datetime
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status: IngestionJobStatus
    cloud_cover_pct: Decimal | None
    valid_pixel_pct: Decimal | None
    error_message: str | None
    stac_item_id: str | None


class RefreshResponse(BaseModel):
    """POST /api/v1/blocks/{block_id}/imagery/refresh response."""

    queued_subscription_ids: tuple[UUID, ...]
    correlation_id: str | None = None


# --- Cursor pagination wrapper ---------------------------------------------


class CursorPage[T](BaseModel):
    """Generic cursor-paginated response. Cursor is opaque; clients echo it back."""

    items: list[T]
    next_cursor: str | None = None


# --- /api/v1/config payload (tenant-scoped tile-server URL) -----------------


class ImageryConfigEntry(BaseModel):
    """Per-product UI hints for the frontend imagery picker."""

    product_id: UUID
    product_code: str
    product_name: str
    bands: tuple[str, ...]
    supported_indices: tuple[str, ...]


class ConfigResponse(BaseModel):
    """GET /api/v1/config response body.

    Tile-server URL is tenant-scoped today (single instance), but the
    contract leaves room for per-tenant routing later. The frontend
    fetches this once on app load and caches in a React context.
    """

    tile_server_base_url: str
    s3_bucket: str
    cloud_cover_visualization_max_pct: int
    cloud_cover_aggregation_max_pct: int
    products: tuple[ImageryConfigEntry, ...]
