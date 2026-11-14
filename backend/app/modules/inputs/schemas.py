"""Wire shapes for the inputs catalogue (D20)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category = Literal[
    "organic_fertiliser",
    "biological_agent",
    "mineral_or_botanical_treatment",
    "foliar_nutrient",
    "growth_regulator",
    "trap_or_bait",
    "bag_or_cover",
]
Method = Literal[
    "basin", "spray", "dust", "release", "trap", "injection", "cover", "foliar", "soil_mix"
]
OrganicStatus = Literal["permitted", "restricted", "not_permitted", "unverified"]
Unit = Literal[
    "kg/plant",
    "g/plant",
    "L/plant/week",
    "cards/plant",
    "kg/plant/year_of_age",
    "g/100 L",
    "mg/L",
    "%",
    "ppm",
    "traps/ha",
    "kg/ha",
    "L/ha",
    "other",
]


class InputDose(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    crop_path: str | None = Field(default=None, max_length=255)
    value: Decimal | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    unit: Unit
    unit_note: str | None = Field(default=None, max_length=255)
    context: str | None = Field(default=None, max_length=1000)
    reference: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _shape(self) -> InputDose:
        if self.value is None and self.value_min is None and self.value_max is None:
            raise ValueError("a dose needs a value, a range, or both")
        if (
            self.value_min is not None
            and self.value_max is not None
            and self.value_min > self.value_max
        ):
            raise ValueError("value_min is above value_max")
        if self.unit == "other" and not self.unit_note:
            raise ValueError("unit 'other' needs a unit_note")
        return self


class InputResponse(BaseModel):
    id: UUID
    scope: Literal["platform", "tenant"]
    code: str
    name_en: str
    name_ar: str | None = None
    category: Category
    active_ingredient: str | None = None
    methods: list[Method]
    organic_status: OrganicStatus
    organic_list: str | None = None
    phi_days: int | None = None
    rei_hours: int | None = None
    crop_paths: list[str]
    notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    doses: list[InputDose] = Field(default_factory=list)


class _InputFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    category: Category | None = None
    active_ingredient: str | None = Field(default=None, max_length=500)
    methods: list[Method] | None = None
    organic_status: OrganicStatus | None = None
    organic_list: str | None = Field(default=None, max_length=500)
    phi_days: int | None = Field(default=None, ge=0, le=3650)
    rei_hours: int | None = Field(default=None, ge=0, le=8760)
    crop_paths: list[str] | None = None
    notes: str | None = Field(default=None, max_length=4000)


class InputCreateRequest(_InputFields):
    code: str = Field(pattern=r"^[a-z0-9_]+$", max_length=100)
    name_en: str = Field(min_length=1, max_length=255)
    category: Category


class InputUpdateRequest(_InputFields):
    is_active: bool | None = None


class InputDosesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doses: list[InputDose] = Field(max_length=50)
