"""Wire shapes for harvest records."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class HarvestLotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harvested_on: date
    weight_kg: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    price_per_kg: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    #: Defaults to the crop assignment active on the block that day.
    block_crop_id: UUID | None = None
    #: Defaults to that assignment's season, else the harvest year.
    season_label: str | None = Field(default=None, max_length=64)
    #: Defaults to the next number in the block's season.
    pick_no: int | None = Field(default=None, ge=1, le=999)
    label: str | None = Field(default=None, max_length=120)
    label_ar: str | None = Field(default=None, max_length=120)
    notes_internal: str | None = Field(default=None, max_length=2000)

    @field_validator("season_label", "label", "label_ar", "notes_internal")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class HarvestLotUpdateRequest(BaseModel):
    """Fields a correction may change. The block and currency are fixed."""

    model_config = ConfigDict(extra="forbid")

    harvested_on: date | None = None
    weight_kg: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    price_per_kg: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=4)
    pick_no: int | None = Field(default=None, ge=1, le=999)
    label: str | None = Field(default=None, max_length=120)
    label_ar: str | None = Field(default=None, max_length=120)
    notes_internal: str | None = Field(default=None, max_length=2000)

    @field_validator("label", "label_ar", "notes_internal")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("harvested_on", "weight_kg", "pick_no", mode="before")
    @classmethod
    def _no_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("omit the field instead of sending null")
        return value


class HarvestLotResponse(BaseModel):
    id: UUID
    farm_id: UUID
    block_id: UUID
    block_crop_id: UUID | None = None
    season_label: str
    pick_no: int
    label: str | None = None
    label_ar: str | None = None
    harvested_on: date
    weight_kg: Decimal
    price_per_kg: Decimal | None = None
    currency: str
    #: weight_kg x price_per_kg, rounded to 2 places; null without a price.
    revenue: Decimal | None = None
    notes_internal: str | None = None
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
