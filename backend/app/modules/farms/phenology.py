"""Validated shapes for phenology stages and canopy size classes.

The catalog stores both as opaque JSONB at three taxonomy levels
(Crop → Variety → Strain). These Pydantic models give that JSON a
*defined, enforced* shape so the auto-advance task, the recommendation
engine, the block UI, and plan-template authoring can all rely on it.

Resolution (deepest non-NULL override wins) lives in
``app.modules.farms.crop_thresholds``; this module only validates a
single level's payload.

Phenology ``advance.mode`` drives how a block moves through the stage:

  * ``days_from_planting`` / ``gdd_from_planting`` — annual crops, anchored
    on ``BlockCrop.planting_date``.
  * ``calendar_doy`` — perennials (the season recurs; planting was years
    ago, so day/GDD-from-planting is meaningless). ``MM-DD`` windows,
    wrap-around allowed (e.g. Dec→Jan).
  * ``manual`` — only advances via the manual transition endpoint.

The mode set allowed for a crop is cross-checked against
``Crop.is_perennial`` at write time — see :func:`validate_phenology_payload`.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,31}$")
_MMDD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")

PERENNIAL_MODES: frozenset[str] = frozenset({"calendar_doy", "manual"})
ANNUAL_MODES: frozenset[str] = frozenset({"days_from_planting", "gdd_from_planting", "manual"})


def _validate_code(value: str) -> str:
    if not _CODE_RE.fullmatch(value):
        raise ValueError("code must match [A-Za-z0-9][A-Za-z0-9_-]{0,31}")
    return value


class _AdvanceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdvanceManual(_AdvanceBase):
    mode: Literal["manual"]


class AdvanceDaysFromPlanting(_AdvanceBase):
    mode: Literal["days_from_planting"]
    start_day: int = Field(ge=0)
    end_day: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> AdvanceDaysFromPlanting:
        if self.end_day <= self.start_day:
            raise ValueError("end_day must be greater than start_day")
        return self


class AdvanceGddFromPlanting(_AdvanceBase):
    mode: Literal["gdd_from_planting"]
    start_gdd: float = Field(ge=0)
    end_gdd: float = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> AdvanceGddFromPlanting:
        if self.end_gdd <= self.start_gdd:
            raise ValueError("end_gdd must be greater than start_gdd")
        return self


class AdvanceCalendarDoy(_AdvanceBase):
    mode: Literal["calendar_doy"]
    # MM-DD; wrap-around (start > end, e.g. 12-01 → 01-31) is allowed and
    # handled by the auto-advance resolver, so no ordering check here.
    start_doy: str
    end_doy: str

    @field_validator("start_doy", "end_doy")
    @classmethod
    def _mmdd(cls, value: str) -> str:
        if not _MMDD_RE.fullmatch(value):
            raise ValueError("doy must be MM-DD (e.g. 03-15)")
        return value


Advance = Annotated[
    AdvanceManual | AdvanceDaysFromPlanting | AdvanceGddFromPlanting | AdvanceCalendarDoy,
    Field(discriminator="mode"),
]


class PhenologyStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str = Field(min_length=1, max_length=255)
    order: int = Field(ge=0)
    advance: Advance
    # FAO-56 crop coefficient for this stage. Optional, because most catalog
    # rows predate it and the irrigation engine falls back to a per-stage
    # table when it is absent.
    #
    # It has to be declared here even though nothing in this module reads it:
    # the model is `extra="forbid"`, so while `irrigation.engine._phenology_kc`
    # has always documented the crop catalog as its PREFERRED Kc source, a
    # catalog carrying one would have failed validation. The preferred path was
    # unreachable until this field existed.
    #
    # Bounded rather than free: FAO-56 single crop coefficients sit roughly
    # 0.2-1.3, so anything at or below zero is a typo and anything above 2 is
    # almost certainly a percentage that lost its decimal point.
    kc: Decimal | None = Field(default=None, gt=0, le=2)

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class PhenologyStages(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[PhenologyStage] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> PhenologyStages:
        codes = [s.code for s in self.stages]
        if len(set(codes)) != len(codes):
            raise ValueError("stage codes must be unique")
        orders = [s.order for s in self.stages]
        if len(set(orders)) != len(orders):
            raise ValueError("stage orders must be unique")
        return self


class SizeClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str = Field(min_length=1, max_length=255)
    order: int = Field(ge=0)

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class SizeClasses(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classes: list[SizeClass] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> SizeClasses:
        codes = [c.code for c in self.classes]
        if len(set(codes)) != len(codes):
            raise ValueError("size class codes must be unique")
        orders = [c.order for c in self.classes]
        if len(set(orders)) != len(orders):
            raise ValueError("size class orders must be unique")
        return self


def validate_phenology_payload(
    data: dict[str, Any], *, is_perennial: bool, has_gdd_base: bool
) -> PhenologyStages:
    """Validate a ``phenology_stages`` payload + cross-check vs the crop.

    Raises ``ValueError`` (incl. ``pydantic.ValidationError``) on a bad
    shape, a mode that doesn't fit the crop's cycle, or a
    ``gdd_from_planting`` stage on a crop without a GDD base temp.
    """
    model = PhenologyStages.model_validate(data)
    allowed = PERENNIAL_MODES if is_perennial else ANNUAL_MODES
    cycle = "perennial" if is_perennial else "annual"
    for stage in model.stages:
        mode = stage.advance.mode
        if mode not in allowed:
            raise ValueError(
                f"stage {stage.code!r}: advance mode {mode!r} is not allowed for a "
                f"{cycle} crop (allowed: {sorted(allowed)})"
            )
        if mode == "gdd_from_planting" and not has_gdd_base:
            raise ValueError(
                f"stage {stage.code!r}: gdd_from_planting requires the crop to set "
                "gdd_base_temp_c"
            )
    return model


def validate_size_classes_payload(data: dict[str, Any]) -> SizeClasses:
    """Validate a ``size_classes`` payload. Raises ``ValueError`` on a bad shape."""
    return SizeClasses.model_validate(data)


__all__ = [
    "ANNUAL_MODES",
    "PERENNIAL_MODES",
    "PhenologyStage",
    "PhenologyStages",
    "SizeClass",
    "SizeClasses",
    "validate_phenology_payload",
    "validate_size_classes_payload",
]
