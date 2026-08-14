"""Pydantic schemas for the imagery module's REST surface.

Wire format follows the conventions in ARCHITECTURE.md § 8: snake_case
JSON keys, RFC 3339 timestamps, m² for areas, cursor-based pagination.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.imagery.farm_aoi import PROCESS_API_MAX_PX_PER_SIDE

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


class FarmSubscriptionCreate(BaseModel):
    """POST /api/v1/farms/{farm_id}/imagery/subscriptions body."""

    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    cadence_hours: int | None = Field(default=None, ge=1)
    cloud_cover_max_pct: int | None = Field(default=None, ge=0, le=100)
    #: Fetch the FARM's own boundary rather than stitching block rasters.
    #: Defaults off: it is a second, larger provider request per pass, so
    #: turning it on is a deliberate act with a quota consequence.
    fetch_farm_aoi: bool = False


class FarmSubscriptionUpdate(BaseModel):
    """PATCH body. Omitted fields are left alone."""

    model_config = ConfigDict(extra="forbid")

    cadence_hours: int | None = Field(default=None, ge=1)
    cloud_cover_max_pct: int | None = Field(default=None, ge=0, le=100)
    fetch_farm_aoi: bool | None = None
    is_active: bool | None = None


class FarmSubscriptionRead(BaseModel):
    """One farm-level imagery subscription."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    product_id: UUID
    cadence_hours: int | None
    cloud_cover_max_pct: int | None
    is_active: bool
    fetch_farm_aoi: bool
    last_successful_ingest_at: datetime | None
    last_attempted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # Whether this farm CAN be fetched as one AOI, measured on read rather
    # than stored: a farm's boundary can be redrawn at any time, and a stored
    # verdict would go stale silently. `fetch_farm_aoi` says which path the
    # farm is on; these say which paths are available to it and why.
    farm_aoi_fetchable: bool = True
    farm_aoi_width_px: int | None = None
    farm_aoi_height_px: int | None = None
    farm_aoi_max_px: int = PROCESS_API_MAX_PX_PER_SIDE


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


class FarmSceneRead(BaseModel):
    """One acquisition day for a farm — a row of the console's scene strip.

    Grouped by DAY rather than by exact ``scene_datetime``. Blocks that fall
    in different Sentinel tiles get slightly different sensing times for what
    a grower calls "the same pass", and a strip with two entries an hour
    apart reads as a bug rather than as precision.

    ``at`` is the instant to send back as the ``at`` bound on grid-cells:
    the end of the day, so every block's observation for that pass is at or
    before it.
    """

    scene_date: date
    at: datetime
    block_count: int
    succeeded_count: int
    skipped_cloud_count: int
    #: Blocks whose INDEX rasters exist for this pass — i.e. how much of the
    #: day can actually be drawn. Ingestion and index computation are separate
    #: tasks and a historical backfill runs only the first, so a day can be
    #: fully "succeeded" and still render nothing. Zero means the pass was
    #: ingested but never processed.
    computed_count: int
    #: Mean across the jobs of the day that reported one; null if none did.
    cloud_cover_pct: Decimal | None


class FarmScenesResponse(BaseModel):
    """GET /api/v1/farms/{farm_id}/scenes response body."""

    farm_id: UUID
    items: tuple[FarmSceneRead, ...]
    #: Median gap between the most recent acquisitions, in days. Null when
    #: there are too few to infer one. The UI turns it into an EXPECTED next
    #: pass — never a promise, since cloud decides whether a pass is usable.
    median_gap_days: float | None


class FarmSceneAssetRead(BaseModel):
    """The index raster to render for one block at one pass.

    ``stac_item_id`` is ``provider/product/scene/aoi`` — every part of the
    asset key except the index code, which the caller appends per the index
    it is drawing. The frontend builds ``{stac_item_id}/{index}.tif`` and
    hands it to the tile server; nothing here needs to know about COGs.
    """

    block_id: UUID
    product_id: UUID
    stac_item_id: str
    scene_datetime: datetime
    #: Ground sample distance in metres — the legend squares it to turn a
    #: pixel count into an area. Null when the product row is unreadable.
    resolution_m: Decimal | None


class FarmRasterRead(BaseModel):
    """One farm-wide raster — the whole farm as a single surface.

    Same ``stac_item_id`` shape as a block asset, so a caller appends
    ``/{index}.tif`` without caring which it is holding. When this is present
    the client should draw THIS and ignore ``items``: it covers the same
    ground in one file, with no seam where blocks meet.
    """

    stac_item_id: str
    scene_datetime: datetime
    resolution_m: Decimal | None
    #: How many block rasters were stitched into it — a farm whose blocks are
    #: partly missing still yields a surface, and this says how complete it is.
    #: None when the surface was FETCHED for the farm boundary: nothing was
    #: merged, so the count does not apply rather than being zero.
    blocks_merged: int | None = None
    #: ``stitched`` from block rasters, or ``fetched`` for the farm boundary.
    #: A fetched surface covers ground no block was drawn around; a stitched
    #: one is only ever as wide as the blocks behind it.
    source: str = "stitched"


class FarmSceneAssetsResponse(BaseModel):
    """GET /api/v1/farms/{farm_id}/scene-assets response body."""

    farm_id: UUID
    #: The bound that was applied, echoed back so a client can tell "latest"
    #: apart from a specific pass it asked for.
    at: datetime | None
    #: The farm-wide raster, when one has been stitched for this pass and the
    #: farm has not been reshaped since. Null means this farm is still on the
    #: per-block path — which is how the cutover runs one farm at a time.
    farm: FarmRasterRead | None = None
    items: tuple[FarmSceneAssetRead, ...]


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
