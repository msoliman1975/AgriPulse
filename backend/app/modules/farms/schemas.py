"""Pydantic request and response models for the farms module.

GeoJSON shapes are typed as plain `dict[str, Any]` plus a field-validator;
introducing a tagged union for Polygon/MultiPolygon would be more
pleasant for clients but every consumer of these endpoints already
parses GeoJSON natively, so the simple dict shape stays out of their way.

Areas come back in `m2` (canonical) **plus** the user's preferred unit
(`area_unit`, `area_value`) — RBAC dependency stamps the unit on
responses via the service layer using the JWT preference.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.farms.crop_attributes import validate_type_consistency

# Codes are ASCII, alnum + dash + underscore, 1-32 chars.
_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,31}$")

FarmType = Literal["commercial", "research", "contract"]
OwnershipType = Literal["owned", "leased", "partnership", "other"]
WaterSource = Literal["well", "canal", "nile", "desalinated", "rainfed", "mixed"]

IrrigationSystem = Literal["drip", "micro_sprinkler", "pivot", "furrow", "flood", "surface", "none"]
IrrigationSource = Literal["well", "canal", "nile", "mixed"]
SoilTexture = Literal[
    "sandy", "sandy_loam", "loam", "clay_loam", "clay", "silty_loam", "silty_clay"
]
SalinityClass = Literal["non_saline", "slightly_saline", "moderately_saline", "strongly_saline"]
BlockCropStatus = Literal["planned", "growing", "harvesting", "completed", "aborted"]

AttachmentKind = Literal["photo", "deed", "soil_test_report", "map", "other"]

UnitName = Literal["feddan", "acre", "hectare"]

FarmRoleName = Literal["FarmManager", "Agronomist", "FieldOperator", "Scout", "Viewer"]


# ---------- Geometry helpers ------------------------------------------------


def _validate_code(value: str) -> str:
    if not _CODE_RE.fullmatch(value):
        raise ValueError("code must match [A-Za-z0-9][A-Za-z0-9_-]{0,31}")
    return value


# ---------- Countries -------------------------------------------------------

# ISO 3166-1 alpha-2: exactly two ASCII letters.
_COUNTRY_CODE_RE = re.compile(r"^[A-Za-z]{2}$")


def _validate_country_code(value: str) -> str:
    if not _COUNTRY_CODE_RE.fullmatch(value):
        raise ValueError("country code must be two letters (ISO 3166-1 alpha-2)")
    return value.upper()


class CountryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name_en: str
    name_ar: str
    is_active: bool = True


class CountryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str = Field(min_length=1, max_length=255)

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_country_code(value)


class CountryUpdateRequest(BaseModel):
    # ``code`` is immutable — it anchors the logical farm + tree references.
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


# ---------- Crops -----------------------------------------------------------


class CropResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name_en: str
    name_ar: str
    scientific_name: str | None
    category: str
    is_perennial: bool
    default_growing_season_days: int | None
    gdd_base_temp_c: Decimal | None = None
    gdd_upper_temp_c: Decimal | None = None
    relevant_indices: list[str]
    phenology_stages: dict[str, Any] | None = None
    default_thresholds: dict[str, Any] | None = None
    size_classes: dict[str, Any] | None = None
    # How deep a block assignment for this crop is classified:
    # crop_only | variety | variety_strain. Drives the picker depth.
    classification_depth: str = "crop_only"
    is_active: bool = True


class CropVarietyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    crop_id: UUID
    code: str
    name_en: str
    name_ar: str | None
    # Canonical hierarchical code "<crop>.<variety>".
    path: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    default_thresholds: dict[str, Any] | None = None
    phenology_stages_override: dict[str, Any] | None = None
    size_classes_override: dict[str, Any] | None = None
    is_active: bool = True


class CropVarietyStrainResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    crop_variety_id: UUID
    code: str
    name_en: str
    name_ar: str | None
    # Canonical hierarchical code "<crop>.<variety>.<strain>".
    path: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    default_thresholds: dict[str, Any] | None = None
    phenology_stages_override: dict[str, Any] | None = None
    size_classes_override: dict[str, Any] | None = None
    is_active: bool = True


class ResolvedTaxonomyResponse(BaseModel):
    """Phenology + size classes resolved (deepest-wins) for a crop path."""

    crop_path: str
    phenology_stages: dict[str, Any] | None = None
    size_classes: dict[str, Any] | None = None


# ---------- Crop catalog authoring (platform-only) --------------------------

ClassificationDepth = Literal["crop_only", "variety", "variety_strain"]


class CropCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    is_perennial: bool = False
    scientific_name: str | None = Field(default=None, max_length=255)
    classification_depth: ClassificationDepth = "crop_only"
    default_growing_season_days: int | None = Field(default=None, ge=1, le=400)
    gdd_base_temp_c: Decimal | None = Field(default=None, ge=0, le=40)
    gdd_upper_temp_c: Decimal | None = Field(default=None, ge=0, le=60)
    relevant_indices: list[str] = Field(default_factory=lambda: ["ndvi"])
    # Validated for shape here; the perennial/annual cross-check happens in
    # the service (it needs the resolved ``is_perennial``).
    phenology_stages: dict[str, Any] | None = None
    default_thresholds: dict[str, Any] | None = None
    size_classes: dict[str, Any] | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class CropUpdateRequest(BaseModel):
    # ``code`` is immutable — it anchors the canonical path on every
    # descendant variety/strain + the denormalized block_crops.crop_path.
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    is_perennial: bool | None = None
    scientific_name: str | None = Field(default=None, max_length=255)
    classification_depth: ClassificationDepth | None = None
    default_growing_season_days: int | None = Field(default=None, ge=1, le=400)
    gdd_base_temp_c: Decimal | None = Field(default=None, ge=0, le=40)
    gdd_upper_temp_c: Decimal | None = Field(default=None, ge=0, le=60)
    relevant_indices: list[str] | None = None
    phenology_stages: dict[str, Any] | None = None
    default_thresholds: dict[str, Any] | None = None
    size_classes: dict[str, Any] | None = None
    is_active: bool | None = None


class CropVarietyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    default_thresholds: dict[str, Any] | None = None
    phenology_stages_override: dict[str, Any] | None = None
    size_classes_override: dict[str, Any] | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class CropVarietyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    default_thresholds: dict[str, Any] | None = None
    phenology_stages_override: dict[str, Any] | None = None
    size_classes_override: dict[str, Any] | None = None
    is_active: bool | None = None


class CropStrainCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    default_thresholds: dict[str, Any] | None = None
    phenology_stages_override: dict[str, Any] | None = None
    size_classes_override: dict[str, Any] | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class CropStrainUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, max_length=255)
    default_thresholds: dict[str, Any] | None = None
    phenology_stages_override: dict[str, Any] | None = None
    size_classes_override: dict[str, Any] | None = None
    is_active: bool | None = None


# ---------- Crop attribute definitions --------------------------------------
#
# Platform-curated typed fields on the crop → block assignment. The DB CHECKs
# pin the coarse invariants (value_type vocabulary, options present iff a
# select type, numeric facets numeric-only); everything cross-field or
# shape-dependent is validated here so the author gets a 422 naming the field
# rather than an opaque IntegrityError.

CropAttributeValueType = Literal[
    "integer", "decimal", "text", "boolean", "date", "single_select", "multi_select"
]


class CropAttributeOption(BaseModel):
    """One choice in a ``single_select`` / ``multi_select``.

    Bilingual by construction: an option list authored EN-only renders as
    English inside an otherwise-Arabic form, which is the exact failure the
    catalog's ``name_en`` / ``name_ar`` pairs exist to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str = Field(min_length=1, max_length=255)
    sort_order: int = 0

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class CropAttributeGate(BaseModel):
    """One-level, non-recursive gate: ``{"code": ..., "in": [...] | "eq": ...}``.

    Exactly one of ``in`` / ``eq`` must be given. No nesting, no boolean
    groups — see ``farms/crop_attributes.py`` for why this stays small.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: str
    # ``in`` is a Python keyword, so the field is ``in_`` with an alias. The
    # stored JSON keeps the wire name; see ``gate_matches``.
    in_: list[str | bool] | None = Field(default=None, alias="in", serialization_alias="in")
    eq: str | bool | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)

    @model_validator(mode="after")
    def _exactly_one_operand(self) -> CropAttributeGate:
        if (self.in_ is None) == (self.eq is None):
            raise ValueError("gate needs exactly one of 'in' or 'eq'")
        if self.in_ is not None and not self.in_:
            raise ValueError("gate 'in' must list at least one value")
        return self


class CropAttributeDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    crop_id: UUID
    crop_variety_id: UUID | None = None
    crop_variety_strain_id: UUID | None = None
    # Canonical path of the node this definition attaches to.
    path: str
    code: str
    name_en: str
    name_ar: str
    description_en: str | None = None
    description_ar: str | None = None
    value_type: CropAttributeValueType
    unit_en: str | None = None
    unit_ar: str | None = None
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    decimal_places: int | None = None
    text_max_length: int | None = None
    options: list[dict[str, Any]] | None = None
    is_required: bool = False
    required_when: dict[str, Any] | None = None
    show_when: dict[str, Any] | None = None
    group_code: str | None = None
    group_name_en: str | None = None
    group_name_ar: str | None = None
    sort_order: int = 0
    is_reportable: bool = True
    is_active: bool = True


class ResolvedCropAttributesResponse(BaseModel):
    """Definitions resolved deepest-wins for a crop path.

    ``shadowed_codes`` names the inherited definitions that a deeper level
    replaced. The platform authoring UI needs it — without it an author edits
    the crop-level row, sees the variety unchanged, and concludes the save
    failed.
    """

    crop_path: str
    definitions: list[CropAttributeDefinitionResponse]
    shadowed_codes: list[str] = Field(default_factory=list)


class _CropAttributeWriteBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CropAttributeDefinitionCreateRequest(_CropAttributeWriteBase):
    # Which taxonomy node this attaches to. Absent → the crop itself.
    # A strain id implies its variety; the service resolves and validates that
    # the node actually belongs to the crop in the path.
    crop_variety_id: UUID | None = None
    crop_variety_strain_id: UUID | None = None

    code: str
    name_en: str = Field(min_length=1, max_length=255)
    name_ar: str = Field(min_length=1, max_length=255)
    description_en: str | None = Field(default=None, max_length=1000)
    description_ar: str | None = Field(default=None, max_length=1000)
    value_type: CropAttributeValueType
    unit_en: str | None = Field(default=None, max_length=32)
    unit_ar: str | None = Field(default=None, max_length=32)
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    decimal_places: int | None = Field(default=None, ge=0, le=4)
    text_max_length: int | None = Field(default=None, ge=1, le=4000)
    options: list[CropAttributeOption] | None = None
    is_required: bool = False
    required_when: CropAttributeGate | None = None
    show_when: CropAttributeGate | None = None
    group_code: str | None = Field(default=None, max_length=64)
    group_name_en: str | None = Field(default=None, max_length=255)
    group_name_ar: str | None = Field(default=None, max_length=255)
    sort_order: int = Field(default=0, ge=0, le=9999)
    is_reportable: bool = True

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)

    @model_validator(mode="after")
    def _consistent(self) -> CropAttributeDefinitionCreateRequest:
        # Shared with the PATCH path in the service — see
        # ``farms/crop_attributes.validate_type_consistency``.
        validate_type_consistency(
            value_type=self.value_type,
            options=self.options,
            value_min=self.value_min,
            value_max=self.value_max,
            decimal_places=self.decimal_places,
            unit_en=self.unit_en,
            unit_ar=self.unit_ar,
            text_max_length=self.text_max_length,
        )
        if self.crop_variety_strain_id is not None and self.crop_variety_id is None:
            raise ValueError("crop_variety_strain_id requires crop_variety_id")
        return self


class CropAttributeDefinitionUpdateRequest(_CropAttributeWriteBase):
    # ``code`` and the taxonomy attachment are immutable: both are part of the
    # identity that stored values point at. Re-pointing a definition would
    # silently re-interpret every value already recorded against it.
    name_en: str | None = Field(default=None, min_length=1, max_length=255)
    name_ar: str | None = Field(default=None, min_length=1, max_length=255)
    description_en: str | None = Field(default=None, max_length=1000)
    description_ar: str | None = Field(default=None, max_length=1000)
    unit_en: str | None = Field(default=None, max_length=32)
    unit_ar: str | None = Field(default=None, max_length=32)
    value_min: Decimal | None = None
    value_max: Decimal | None = None
    decimal_places: int | None = Field(default=None, ge=0, le=4)
    text_max_length: int | None = Field(default=None, ge=1, le=4000)
    options: list[CropAttributeOption] | None = None
    is_required: bool | None = None
    required_when: CropAttributeGate | None = None
    show_when: CropAttributeGate | None = None
    group_code: str | None = Field(default=None, max_length=64)
    group_name_en: str | None = Field(default=None, max_length=255)
    group_name_ar: str | None = Field(default=None, max_length=255)
    sort_order: int | None = Field(default=None, ge=0, le=9999)
    is_reportable: bool | None = None
    is_active: bool | None = None


class BlockCropAttributesResponse(BaseModel):
    """Resolved definitions + current values for one crop → block assignment.

    Definitions ship with the values so the form can render, gate and validate
    from a single response — a second round trip to the catalog is how the
    form and the server end up disagreeing about which fields are required.
    """

    block_crop_id: UUID
    crop_path: str
    definitions: list[CropAttributeDefinitionResponse]
    values: dict[str, Any] = Field(default_factory=dict)


class BlockCropAttributesWriteRequest(BaseModel):
    """PUT body — the whole visible form, not one field.

    Requiredness depends on a gate, and the gate depends on a sibling field's
    value, so a per-field write could land a state the form itself rejects.
    Omitted codes keep their stored value; a code sent as ``null`` clears it.
    """

    model_config = ConfigDict(extra="forbid")

    attributes: dict[str, Any] = Field(default_factory=dict)


class BlockCropAttributeHistoryEntry(BaseModel):
    id: UUID
    block_crop_id: UUID
    definition_id: UUID
    definition_code: str
    value: Any = None
    previous_value: Any = None
    # set | updated | cleared | cleared_by_gate — the last distinguishes a
    # value dropped because its gate closed from one a user cleared.
    change_kind: str
    changed_at: datetime
    changed_by: UUID | None = None


# ---------- Farms -----------------------------------------------------------


class FarmCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    boundary: dict[str, Any] = Field(description="GeoJSON MultiPolygon (SRID 4326).")
    elevation_m: Decimal | None = None
    country_code: str | None = None
    governorate: str | None = None
    district: str | None = None
    nearest_city: str | None = None
    address_line: str | None = None
    farm_type: FarmType = "commercial"
    ownership_type: OwnershipType | None = None
    primary_water_source: WaterSource | None = None
    established_date: date | None = None
    tags: list[str] = Field(default_factory=list)
    # Optional explicit activation date. Defaults to today server-side.
    # Allowed in past (historic backfill) or future (planned activation).
    active_from: date | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)

    @field_validator("country_code")
    @classmethod
    def _country_code_pattern(cls, value: str | None) -> str | None:
        return _validate_country_code(value) if value is not None else None


class FarmUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    boundary: dict[str, Any] | None = None
    elevation_m: Decimal | None = None
    country_code: str | None = None
    governorate: str | None = None
    district: str | None = None
    nearest_city: str | None = None
    address_line: str | None = None
    farm_type: FarmType | None = None
    ownership_type: OwnershipType | None = None
    primary_water_source: WaterSource | None = None
    established_date: date | None = None
    tags: list[str] | None = None

    @field_validator("country_code")
    @classmethod
    def _country_code_pattern(cls, value: str | None) -> str | None:
        return _validate_country_code(value) if value is not None else None


class FarmManagerRef(BaseModel):
    """The farm's primary manager — derived, read-only (U-4a).

    Resolved from the active ``FarmManager`` farm-scope with the earliest
    grant; ``null`` when the farm has no FarmManager assigned. Replaces the
    dropped ``farm_manager_id`` column (tenant migration 0045).
    """

    membership_id: UUID
    full_name: str | None = None


class FarmResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    centroid: dict[str, Any] = Field(description="GeoJSON Point (SRID 4326).")
    area_m2: Decimal
    area_value: Decimal
    area_unit: UnitName
    elevation_m: Decimal | None
    country_code: str | None = None
    governorate: str | None
    district: str | None
    nearest_city: str | None
    address_line: str | None
    farm_type: FarmType
    ownership_type: OwnershipType | None
    primary_water_source: WaterSource | None
    established_date: date | None
    tags: list[str]
    active_from: date
    active_to: date | None
    is_active: bool
    # Derived, read-only — the active FarmManager farm-scope holder (U-4a).
    farm_manager: FarmManagerRef | None = None
    # Defaults bucket (Shared) — surfaced read-only in PR-1; full
    # template authoring + lock semantics arrive in PR-2 / PR-3.
    default_irrigation_system: IrrigationSystem | None = None
    default_irrigation_source: IrrigationSource | None = None
    default_flow_rate_m3_per_hour: Decimal | None = None
    default_tags: list[str] = Field(default_factory=list)
    subscriptions_locked: bool = False
    irrigation_locked: bool = False
    org_locked: bool = False
    created_at: datetime
    updated_at: datetime


class FarmDetailResponse(FarmResponse):
    boundary: dict[str, Any] = Field(description="GeoJSON MultiPolygon (SRID 4326).")


class FarmInactivationRequest(BaseModel):
    """POST /api/v1/farms/{id}:inactivate body."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class FarmInactivationPreviewResponse(BaseModel):
    """Counts surfaced in the confirm-modal before the user commits."""

    block_count: int
    alerts_resolved: int
    irrigation_skipped: int
    plan_activities_skipped: int
    weather_subs_deactivated: int
    imagery_subs_deactivated: int


class FarmInactivationResponse(FarmInactivationPreviewResponse):
    farm_id: UUID
    active_to: date


class FarmReactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restore_blocks: bool = Field(
        default=False,
        description=(
            "When true, every block currently inactive under this farm is " "also reactivated."
        ),
    )


class FarmReactivationResponse(BaseModel):
    farm_id: UUID
    restored_block_count: int
    # Subscriptions re-enabled by reversing the inactivation cascade (only
    # those the cascade itself had turned off). 0 when restore_blocks=False.
    weather_subs_reactivated: int = 0
    imagery_subs_reactivated: int = 0


# ---------- Blocks ----------------------------------------------------------


UnitType = Literal["block", "pivot", "pivot_sector"]


class BlockCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str | None = Field(default=None, max_length=255)
    boundary: dict[str, Any] = Field(description="GeoJSON Polygon (SRID 4326).")
    elevation_m: Decimal | None = None
    irrigation_system: IrrigationSystem | None = None
    irrigation_source: IrrigationSource | None = None
    soil_texture: SoilTexture | None = None
    salinity_class: SalinityClass | None = None
    soil_ph: Decimal | None = Field(default=None, ge=0, le=14)
    # U-4b: per-block agronomist, referenced by tenant membership_id.
    agronomist_membership_id: UUID | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Land-unit polymorphism: defaults to plain `block` so existing
    # creation flows work unchanged. `pivot_sector` requires
    # `parent_unit_id`; `block` and `pivot` must leave it null.
    unit_type: UnitType = "block"
    parent_unit_id: UUID | None = None
    irrigation_geometry: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Provider-agnostic JSON for pivot/sector geometry: "
            "`{center: {lat, lon}, radius_m, start_angle_deg?, end_angle_deg?}`."
        ),
    )
    # Optional explicit activation date. Defaults to today server-side.
    active_from: date | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class BlockUpdateRequest(BaseModel):
    """Update block. Geometry edits and metadata edits use different RBAC."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    boundary: dict[str, Any] | None = None
    elevation_m: Decimal | None = None
    irrigation_system: IrrigationSystem | None = None
    irrigation_source: IrrigationSource | None = None
    soil_texture: SoilTexture | None = None
    salinity_class: SalinityClass | None = None
    soil_ph: Decimal | None = Field(default=None, ge=0, le=14)
    agronomist_membership_id: UUID | None = None
    notes: str | None = None
    tags: list[str] | None = None
    irrigation_geometry: dict[str, Any] | None = None


class BlockResponsibleRequest(BaseModel):
    """PUT /blocks/{id}/responsible — hand the block to a member.

    Its own request rather than a field on the block update, because a handover
    carries a reason and the generic update does not.
    """

    model_config = ConfigDict(extra="forbid")

    # NULL is a legitimate value: unassigning is a change worth recording, and
    # it is the state that makes dispatch fall back to an arbitrary member.
    membership_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class BlockResponsibleLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    previous_membership_id: UUID | None
    new_membership_id: UUID | None
    note: str | None
    changed_at: datetime
    changed_by: UUID | None


class BlockResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    code: str
    name: str | None
    centroid: dict[str, Any]
    area_m2: Decimal
    area_value: Decimal
    area_unit: UnitName
    aoi_hash: str
    elevation_m: Decimal | None
    irrigation_system: IrrigationSystem | None
    irrigation_source: IrrigationSource | None
    soil_texture: SoilTexture | None
    salinity_class: SalinityClass | None
    soil_ph: Decimal | None
    agronomist_membership_id: UUID | None
    notes: str | None
    tags: list[str]
    active_from: date
    active_to: date | None
    is_active: bool
    unit_type: UnitType
    parent_unit_id: UUID | None
    irrigation_geometry: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class BlockDetailResponse(BlockResponse):
    boundary: dict[str, Any]


class BlockListItemResponse(BlockResponse):
    """List row, optionally carrying the boundary.

    `GET /farms/{id}/blocks?include_boundary=true` lets a map client fetch
    every polygon in ONE request. Without it the map had to follow the list
    with one `GET /blocks/{id}` per block, which at a few dozen blocks
    exhausts the API's DB connection pool and fails the whole page load.
    Defaults to null so existing list consumers see an unchanged payload
    shape apart from the extra key.
    """

    boundary: dict[str, Any] | None = None


class BlockInactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class BlockInactivationPreviewResponse(BaseModel):
    alerts_resolved: int
    irrigation_skipped: int
    plan_activities_skipped: int
    weather_subs_deactivated: int
    imagery_subs_deactivated: int


class BlockInactivationResponse(BlockInactivationPreviewResponse):
    block_id: UUID
    farm_id: UUID
    active_to: date


class BlockReactivationResponse(BaseModel):
    block_id: UUID
    farm_id: UUID
    # Subscriptions re-enabled by reversing the inactivation cascade (only
    # those the cascade itself had turned off).
    weather_subs_reactivated: int = 0
    imagery_subs_reactivated: int = 0


# ---------- Bulk block create from uploaded AOI files ---------------------

# Per-row outcome of a bulk reconcile. Identity is the block *code*:
#   created               — new code, block inserted
#   reused                — code exists with an identical boundary; existing
#                           block kept as-is, nothing written
#   replaced_deleted      — code exists with a changed boundary and the old
#                           block was pristine (no dependents) → hard-deleted,
#                           new block inserted
#   replaced_inactivated  — code exists with a changed boundary and the old
#                           block owned data → soft-inactivated (cascade), new
#                           block inserted
#   error                 — row could not be processed (see error_code)
BulkBlockStatus = Literal[
    "created",
    "reused",
    "replaced_deleted",
    "replaced_inactivated",
    "error",
]


class BulkBlockItem(BaseModel):
    """One AOI-derived candidate block. Code/geometry are validated per-row
    in the service (not via a raising field-validator) so one malformed row
    yields an ``error`` outcome instead of failing the whole batch."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str | None = Field(default=None, max_length=255)
    boundary: dict[str, Any] = Field(description="GeoJSON Polygon (SRID 4326).")


class BulkBlockCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BulkBlockItem] = Field(min_length=1, max_length=200)
    # The client shows a destructive-action summary and the user confirms
    # before this is set. When False, any row that would delete/inactivate an
    # existing block is returned as an ``error`` (``replace_not_confirmed``)
    # instead of executing — so a destructive replace never happens silently.
    allow_replace: bool = False


class BulkBlockResultRow(BaseModel):
    # Echoes the submitted index so the client can map results back to rows.
    index: int
    code: str
    status: BulkBlockStatus
    # New block id for created/replaced_*, existing id for reused, null on error.
    block_id: UUID | None = None
    # For replaced_*: the id of the old block that was deleted/inactivated.
    replaced_block_id: UUID | None = None
    # Machine-readable reason when status == "error".
    error_code: str | None = None
    # Human-facing note (translated client-side by error_code where relevant).
    message: str | None = None


class BulkBlockCreateResponse(BaseModel):
    results: list[BulkBlockResultRow]
    created: int
    reused: int
    replaced: int
    errors: int


# ---------- Pivot + sectors atomic create ---------------------------------


class PivotCenter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PivotCreateRequest(BaseModel):
    """POST /api/v1/farms/{farm_id}/pivots body."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str | None = Field(default=None, max_length=255)
    center: PivotCenter
    radius_m: float = Field(gt=0, le=5000)
    # 1..16 keeps the UI cohort sane; equal-angle slicing.
    sector_count: int = Field(ge=1, le=16)
    irrigation_system: IrrigationSystem | None = "pivot"
    active_from: date | None = None

    @field_validator("code")
    @classmethod
    def _code_pattern(cls, value: str) -> str:
        return _validate_code(value)


class PivotCreateResponse(BaseModel):
    pivot: BlockDetailResponse
    sectors: list[BlockDetailResponse]


# ---------- Auto-grid -------------------------------------------------------


class AutoGridRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The grid can be driven either by a cell edge (``cell_size_m``) or by a
    # per-block maximum area (``max_area_m2``, the canonical unit — the client
    # converts from the user's preferred area unit). When ``max_area_m2`` is
    # supplied it wins, and the derived (clamped) ``cell_size_m`` is echoed in
    # the response so the UI can show the effective grid.
    cell_size_m: int = Field(default=500, ge=10, le=5000)
    max_area_m2: float | None = Field(default=None, gt=0)


class AutoGridCandidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    boundary: dict[str, Any]
    area_m2: Decimal


class AutoGridResponse(BaseModel):
    cell_size_m: int
    candidates: list[AutoGridCandidate]


# ---------- Block crops -----------------------------------------------------


class BlockCropAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crop_id: UUID
    crop_variety_id: UUID | None = None
    crop_variety_strain_id: UUID | None = None
    season_label: str = Field(min_length=1, max_length=64)
    # Valid time. `effective_from` defaults to `planting_date`, else today —
    # they coincide in the common case, so the form need not ask twice.
    # `effective_to = None` means ongoing, which is the normal state for a
    # perennial. Assigning a crop auto-closes the block's open assignment at
    # `effective_from`; a bounded one is never rewritten.
    effective_from: date | None = None
    effective_to: date | None = None
    planting_date: date | None = None
    # One of the crop's resolved ``size_classes`` codes (validated server-side).
    canopy_size_class: str | None = None
    notes: str | None = None
    # Crop fields for the assignment being created, `{code: value}`.
    #
    # Sent with the assignment rather than in a follow-up PUT so the whole
    # thing is one transaction: a required attribute that fails validation
    # rolls the assignment back instead of leaving a half-configured one
    # behind. The definitions come from the crop's catalog entry, which the
    # form resolves from the chosen crop path before the assignment exists.
    attributes: dict[str, Any] = Field(default_factory=dict)
    make_current: bool = True


class BlockCropUpdateRequest(BaseModel):
    # Growth stage is intentionally NOT settable here — it has its own
    # transition endpoint that appends to GrowthStageLog. This patch covers
    # the agronomy/lifecycle fields editable in place.
    model_config = ConfigDict(extra="forbid")

    canopy_size_class: str | None = None
    growth_stage_locked: bool | None = None
    actual_harvest_date: date | None = None
    status: BlockCropStatus | None = None
    notes: str | None = None


class BlockCropResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    crop_id: UUID
    crop_variety_id: UUID | None
    crop_variety_strain_id: UUID | None = None
    crop_path: str = ""
    season_label: str
    # Valid time, half-open [from, to). `effective_to = None` means ongoing.
    effective_from: date
    effective_to: date | None = None
    # Derived from the range against today — NOT the stored `is_current`
    # column, which only moves when someone assigns a crop.
    is_active_now: bool = False
    # past | current | scheduled
    validity_state: str = "past"
    planting_date: date | None
    actual_harvest_date: date | None
    canopy_size_class: str | None = None
    growth_stage: str | None
    growth_stage_updated_at: datetime | None
    growth_stage_locked: bool = False
    is_current: bool
    status: BlockCropStatus
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Bulk crop assignment -------------------------------------------
#
# One set of values written across many blocks of one farm. Three endpoints:
# candidates (what can be targeted, and what it already carries), preview
# (what *would* happen, no writes), apply (do it, reporting per block).
#
# Preview and apply take the SAME request body deliberately — a preview the
# user approves and an apply that then behaves differently is the failure this
# whole surface exists to avoid.

# What to do about a block that already has an open assignment.
BulkConflictMode = Literal["skip", "replace"]

# Preview verbs are future tense, apply verbs are past tense, so a client can
# never render "assigned" for something that has not been written yet.
BulkPreviewOutcome = Literal["assign", "replace", "skip"]
BulkApplyOutcome = Literal["assigned", "replaced", "skipped", "failed"]


class FarmCropAssignmentResponse(BaseModel):
    """The crop one block carried on one date.

    Serves the Farm Console map label, which can be scrubbed back to a scene
    from a past season. Reading `is_active_now` off the per-block history would
    label every historical scene with today's crop, so the date is a parameter
    and the answer is the assignment whose validity range contains it.

    The crop name ships in both languages rather than resolved server-side:
    the caller already localizes every other catalogue name at read time, and
    a locale switch must not need a refetch.
    """

    block_id: UUID
    block_crop_id: UUID
    crop_id: UUID
    crop_path: str
    crop_name_en: str
    crop_name_ar: str
    # Variety and strain, so a caller can render the whole assignment the way
    # the Block Dock already does ("Mango · Alphonso"). Null at a level the
    # crop's `classification_depth` does not reach.
    variety_name_en: str | None = None
    variety_name_ar: str | None = None
    strain_name_en: str | None = None
    strain_name_ar: str | None = None
    season_label: str
    effective_from: date
    effective_to: date | None = None
    status: BlockCropStatus


class BulkCropCandidateCurrent(BaseModel):
    """The assignment a candidate block carries today, if any."""

    block_crop_id: UUID
    crop_path: str
    season_label: str
    planting_date: date | None = None
    effective_from: date
    status: BlockCropStatus


class BulkCropCandidateResponse(BaseModel):
    """A block the bulk run could target, plus what it already holds."""

    block_id: UUID
    code: str
    name: str | None = None
    area_value: Decimal
    area_unit: UnitName
    unit_type: UnitType
    # Null when the block has no assignment covering today.
    current: BulkCropCandidateCurrent | None = None


class BulkCropAssignmentTarget(BaseModel):
    """One block in the run, with the fields allowed to differ from the shared
    values. Everything else is uniform across the run by design — a fully
    per-block payload is just the single-block endpoint in a loop."""

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    # Null/omitted means "use the run's shared value".
    season_label: str | None = Field(default=None, min_length=1, max_length=64)
    planting_date: date | None = None


class BulkCropAssignmentRequest(BaseModel):
    """Body for both `:preview` and the apply POST."""

    model_config = ConfigDict(extra="forbid")

    conflict_mode: BulkConflictMode = "skip"
    targets: list[BulkCropAssignmentTarget] = Field(min_length=1, max_length=500)

    # ---- shared assignment values (mirror BlockCropAssignRequest) ----
    crop_id: UUID
    crop_variety_id: UUID | None = None
    crop_variety_strain_id: UUID | None = None
    season_label: str = Field(min_length=1, max_length=64)
    effective_from: date | None = None
    planting_date: date | None = None
    canopy_size_class: str | None = None
    notes: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("targets")
    @classmethod
    def _no_duplicate_blocks(
        cls, v: list[BulkCropAssignmentTarget]
    ) -> list[BulkCropAssignmentTarget]:
        # Two entries for one block would write two assignments whose ranges
        # overlap; the second fails on the exclusion constraint and the run
        # reports a confusing partial failure. Reject it up front instead.
        seen = {t.block_id for t in v}
        if len(seen) != len(v):
            raise ValueError("targets contains the same block more than once")
        return v


class BulkCropAssignmentPlanned(BaseModel):
    """The assignment a block would receive (or did)."""

    crop_path: str
    season_label: str
    planting_date: date | None = None
    effective_from: date


class BulkCropPreviewItem(BaseModel):
    block_id: UUID
    code: str
    name: str | None = None
    outcome: BulkPreviewOutcome
    # What the block holds now; null when unassigned.
    before: BulkCropCandidateCurrent | None = None
    # What it would hold; null when the run would leave it alone.
    after: BulkCropAssignmentPlanned | None = None
    # Set when a per-block override changed season or planting date.
    overridden: bool = False
    # Why a block is being skipped, in words the UI can show as-is.
    detail: str | None = None


class BulkCropPreviewResponse(BaseModel):
    farm_id: UUID
    conflict_mode: BulkConflictMode
    crop_path: str
    assign_count: int
    replace_count: int
    skip_count: int
    items: list[BulkCropPreviewItem]


class BulkCropApplyItem(BaseModel):
    block_id: UUID
    code: str
    name: str | None = None
    outcome: BulkApplyOutcome
    before: BulkCropCandidateCurrent | None = None
    after: BulkCropAssignmentPlanned | None = None
    overridden: bool = False
    # The new assignment on success; null on skip/failure.
    block_crop_id: UUID | None = None
    # Skip reason or failure message.
    detail: str | None = None


class BulkCropApplyResponse(BaseModel):
    farm_id: UUID
    conflict_mode: BulkConflictMode
    crop_path: str
    applied_count: int
    skipped_count: int
    failed_count: int
    items: list[BulkCropApplyItem]


# ---------- Bulk crop-assignment removal ------------------------------------
#
# Erasing assignments entered by mistake. This is a HARD delete: the rows are
# gone, and `deleted_at` is deliberately not used. There is therefore no undo,
# which is precisely why `:remove-preview` exists and why the response counts
# the dependent rows that go with them.


class BulkCropRemovalRequest(BaseModel):
    """Body for both `:remove-preview` and `:remove`.

    Exactly one selector. ``block_ids`` is the blunt instrument — every
    assignment on those blocks, history included. ``block_crop_ids`` is the
    surgical one behind "undo this run", which knows the ids it just created
    and must not touch anything else on the same block.
    """

    model_config = ConfigDict(extra="forbid")

    block_ids: list[UUID] | None = Field(default=None, max_length=500)
    block_crop_ids: list[UUID] | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> BulkCropRemovalRequest:
        chosen = [s for s in (self.block_ids, self.block_crop_ids) if s is not None]
        if len(chosen) != 1:
            raise ValueError("provide exactly one of block_ids or block_crop_ids")
        if not chosen[0]:
            raise ValueError("the selector must not be empty")
        if len(set(chosen[0])) != len(chosen[0]):
            raise ValueError("the selector contains duplicates")
        return self


class BulkCropRemovalAssignment(BaseModel):
    """One assignment that would be (or was) destroyed."""

    block_crop_id: UUID
    crop_path: str
    season_label: str
    effective_from: date
    effective_to: date | None = None
    is_current: bool


class BulkCropRemovalItem(BaseModel):
    block_id: UUID
    code: str
    name: str | None = None
    # Named so a client cannot mistake a preview for a result.
    assignments: list[BulkCropRemovalAssignment]
    removed_count: int = 0
    detail: str | None = None


class BulkCropRemovalResponse(BaseModel):
    farm_id: UUID
    block_count: int
    assignment_count: int
    # Cascade fallout, spelled out because a hard delete cannot be undone and
    # these rows would otherwise disappear silently.
    attribute_value_count: int
    attribute_value_log_count: int
    growth_stage_log_count: int
    # Not a cascade — `recommendations.block_crop_id` has no FK, so these are
    # nulled explicitly rather than deleted.
    recommendation_unlink_count: int
    # Assignments a `replace` run auto-closed that this removal un-closes, so
    # undoing a run restores the crop the block had before it.
    reopened_count: int = 0
    items: list[BulkCropRemovalItem]


# ---------- Growth-stage logs ----------------------------------------------

GrowthStageSource = Literal["manual", "derived", "imported"]


class GrowthStageTransitionRequest(BaseModel):
    """POST /api/v1/blocks/{block_id}/growth-stages body."""

    model_config = ConfigDict(extra="forbid")

    stage: str = Field(min_length=1, max_length=64)
    source: GrowthStageSource = "manual"
    transition_date: datetime | None = None
    block_crop_id: UUID | None = Field(
        default=None,
        description=(
            "Optionally link the transition to a specific crop assignment. "
            "Defaults to the block's current crop if any."
        ),
    )
    notes: str | None = Field(default=None, max_length=2000)


class GrowthStageLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    block_crop_id: UUID | None
    stage: str
    source: GrowthStageSource
    confirmed_by: UUID | None
    transition_date: datetime
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Members ---------------------------------------------------------


class FarmMemberAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    membership_id: UUID
    role: FarmRoleName


class FarmMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    membership_id: UUID
    farm_id: UUID
    role: FarmRoleName
    granted_at: datetime
    revoked_at: datetime | None


# ---------- Attachments -----------------------------------------------------

# Cap aligned with prompt-02 § PR-C: 25 MB is enough for high-res phone
# photos and PDF documents without inviting bulk-data uploads.
ATTACHMENT_MAX_BYTES: int = 25 * 1024 * 1024


class AttachmentUploadInitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AttachmentKind
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=ATTACHMENT_MAX_BYTES)


class AttachmentUploadInitResponse(BaseModel):
    """Response from `init`: client uses these fields to PUT to S3 directly."""

    attachment_id: UUID
    s3_key: str
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime


class AttachmentFinalizeRequest(BaseModel):
    """Body of the post-upload finalize call.

    `attachment_id` and `s3_key` come from the init response; the client
    echoes both. The remaining fields populate the row.
    """

    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID
    s3_key: str
    kind: AttachmentKind
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=ATTACHMENT_MAX_BYTES)
    caption: str | None = Field(default=None, max_length=2000)
    taken_at: datetime | None = None
    geo_point: dict[str, Any] | None = Field(default=None, description="GeoJSON Point (SRID 4326).")

    @field_validator("geo_point")
    @classmethod
    def _validate_point(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if value.get("type") != "Point":
            raise ValueError("geo_point must be a GeoJSON Point")
        coords = value.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError("geo_point.coordinates must be [lon, lat]")
        return value


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_kind: Literal["farm", "block"]
    owner_id: UUID
    kind: AttachmentKind
    s3_key: str
    original_filename: str
    content_type: str
    size_bytes: int
    caption: str | None
    taken_at: datetime | None
    geo_point: dict[str, Any] | None
    download_url: str
    download_url_expires_at: datetime
    created_at: datetime
    updated_at: datetime
