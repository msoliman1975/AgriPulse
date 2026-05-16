"""Pydantic wire models for the farm-config endpoints.

Kept in a separate file from ``schemas.py`` to keep PR-2 changes
contained — the rest of the farms module is mature enough that
sprinkling new models into the giant schemas.py would make rebases
painful.
"""

from __future__ import annotations

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
    will_add: list[dict] = Field(default_factory=list)
    will_update: list[dict] = Field(default_factory=list)
    will_deactivate: list[dict] = Field(default_factory=list)
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
