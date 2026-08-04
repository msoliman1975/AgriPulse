"""Pydantic wire models for the farm-config endpoints.

Kept in a separate file from ``schemas.py`` to keep PR-2 changes
contained — the rest of the farms module is mature enough that
sprinkling new models into the giant schemas.py would make rebases
painful.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Template rows ---------------------------------------------------


class ImageryTemplateRowSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    cadence_hours: int = Field(gt=0)
    cloud_cover_max_pct: int | None = Field(default=None, ge=0, le=100)
    is_active: bool = True


class WeatherTemplateRowSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(min_length=1, max_length=64)
    cadence_hours: int = Field(gt=0)
    is_active: bool = True


# ---------- GET / PUT template ----------------------------------------------


class SubscriptionsTemplateResponse(BaseModel):
    imagery: list[ImageryTemplateRowSchema]
    weather: list[WeatherTemplateRowSchema]


class SubscriptionsTemplateReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imagery: list[ImageryTemplateRowSchema] = Field(default_factory=list)
    weather: list[WeatherTemplateRowSchema] = Field(default_factory=list)


# ---------- Apply preview ---------------------------------------------------


class ApplyPreviewRequest(BaseModel):
    """Body for POST .../apply-preview and .../apply.

    Empty / omitted ``block_ids`` means "all active blocks under the
    farm". The UI always submits the explicit list so the user can
    uncheck individual blocks.
    """

    model_config = ConfigDict(extra="forbid")

    block_ids: list[UUID] | None = None


class BlockDiffSchema(BaseModel):
    block_id: UUID
    will_add: list[dict[str, Any]] = Field(default_factory=list)
    will_update: list[dict[str, Any]] = Field(default_factory=list)
    will_deactivate: list[dict[str, Any]] = Field(default_factory=list)
    matches: bool


class ApplyPreviewResponse(BaseModel):
    imagery: list[BlockDiffSchema]
    weather: list[BlockDiffSchema]
    total_blocks: int
    matched_blocks: int


# ---------- Apply -----------------------------------------------------------


class ApplyResponse(BaseModel):
    blocks_touched: int
    imagery_added: int
    imagery_updated: int
    imagery_deactivated: int
    weather_added: int
    weather_updated: int
    weather_deactivated: int


# ---------- PR-3: Locks ----------------------------------------------------


class LockStateResponse(BaseModel):
    subscriptions: bool
    irrigation: bool
    org: bool
    grid: bool


class LockToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force_overwrite: bool = False


# ---------- PR-3: Irrigation template -------------------------------------


class IrrigationTemplateSchema(BaseModel):
    """The shape of farm-level irrigation defaults. All nullable."""

    model_config = ConfigDict(extra="forbid")

    irrigation_system: str | None = None
    irrigation_source: str | None = None
    flow_rate_m3_per_hour: float | None = Field(default=None, ge=0)


class SimpleBlockDiffSchema(BaseModel):
    block_id: str
    before: dict[str, Any]
    after: dict[str, Any]
    matches: bool


class SimpleApplyPreviewResponse(BaseModel):
    blocks: list[SimpleBlockDiffSchema]
    total_blocks: int
    matched_blocks: int


class SimpleApplyResponse(BaseModel):
    blocks_touched: int
    total_blocks: int


# ---------- PR-3: Org template --------------------------------------------


class OrgTemplateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_tags: list[str] = Field(default_factory=list)


# ---------- Grid template (cell size + anomaly threshold) ------------------


class GridTemplateSchema(BaseModel):
    """Farm-level grid defaults. Both nullable — NULL means "not set"."""

    model_config = ConfigDict(extra="forbid")

    cell_size_m: float | None = Field(default=None, gt=0)
    anomaly_z_threshold: float | None = Field(default=None, gt=0)


# The two scopes are separate requests on purpose. One is a sensitivity
# tweak, the other retires geometry and spends compute; collapsing them
# into a single "apply the template" button is how an operator ends up
# rezoning a farm while meaning to nudge a threshold.
GridScope = Literal["threshold", "cell_size"]


class GridApplyRequest(BaseModel):
    """Body for the grid apply-preview / apply endpoints.

    ``clear_override=True`` (threshold scope only) ignores the template's
    threshold and instead clears each block's own override so it inherits
    tenant → platform again. Without it, applying a farm threshold would
    be a one-way door.

    ``confirm_farm_name`` is required by the *apply* endpoint whenever the
    plan contains a rezone. It is checked server-side rather than being
    left to the UI: the destructive path must not be reachable by a
    client that simply doesn't render the confirmation.

    ``backfill_budget_scenes`` bounds the recompute fan-out. ``None``
    means "everything"; ``0`` means "rezone but queue no backfill", which
    is legitimate but leaves all history on the older geometry.
    """

    model_config = ConfigDict(extra="forbid")

    block_ids: list[UUID] | None = None
    scope: GridScope = "threshold"
    clear_override: bool = False
    confirm_farm_name: str | None = None
    backfill_budget_scenes: int | None = Field(default=None, ge=0)


class GridPlanRowSchema(BaseModel):
    block_id: UUID
    block_code: str
    block_name: str | None
    product_id: UUID | None
    product_code: str | None
    product_name: str | None
    native_pixel_m: float | None
    current_cell_size_m: float | None
    current_anomaly_z_threshold: float | None
    target_anomaly_z_threshold: float | None
    target_cell_size_m: float | None = None
    action: str
    reason: str
    matches: bool
    # Scenes currently readable on this row's live geometry. For a rezone
    # this is what stops being readable until the backfill regenerates it.
    scenes_affected: int = 0


class GridApplyPreviewResponse(BaseModel):
    rows: list[GridPlanRowSchema]
    total_rows: int
    changed_rows: int
    unchanged_rows: int
    skipped_rows: int
    # True when Apply would write nothing. The UI disables Confirm on this
    # and reports a zero-change apply as a warning rather than success.
    is_noop: bool
    rezone_rows: int = 0
    create_rows: int = 0
    blocked_rows: int = 0
    scenes_affected: int = 0
    # Drives the type-the-farm-name confirmation. True only when live
    # geometry would be retired — a farm being gridded for the first time
    # must not train operators to type past the confirmation.
    requires_confirmation: bool = False


class GridApplyResponse(BaseModel):
    blocks_touched: int
    total_blocks: int
    # Cell-size scope only. `scenes_stranded` is the honest half: scenes
    # the budget did not reach, which stay on the older geometry.
    scenes_queued: int = 0
    scenes_stranded: int = 0
