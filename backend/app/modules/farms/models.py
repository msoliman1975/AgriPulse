"""Farms ORM models. Crop catalog in `public`; farms/blocks/attachments in
the per-tenant schema (no `__table_args__["schema"]` — search_path resolves).
data_model § 5.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class Country(Base, TimestampedMixin):
    """Curated country catalog in `public`. Read-mostly; tenants only read.

    Referenced logically (no DB FK) by ``farms.country_code`` and by Decision
    Tree ``country_codes`` targeting. ``code`` is ISO 3166-1 alpha-2, immutable.
    """

    __tablename__ = "countries"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class Crop(Base, TimestampedMixin):
    """Curated crop catalog in `public`. Read-mostly; tenants only read."""

    __tablename__ = "crops"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    scientific_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    is_perennial: Mapped[bool] = mapped_column(Boolean, nullable=False)
    default_growing_season_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gdd_base_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    gdd_upper_temp_c: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)
    relevant_indices: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY['ndvi']::text[]"),
    )
    phenology_stages: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Platform-curated rule thresholds inherited by every variety —
    # see `app.modules.farms.crop_thresholds.resolve` for merge rules.
    default_thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Canopy size-class lookup ``{"classes": [{code, name_en, name_ar, order}]}``.
    # Resolved deepest-wins like phenology; surfaced as the block size dropdown.
    size_classes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    # How deep a block assignment for this crop is classified, and thus
    # how deep its canonical path goes:
    #   crop_only      -> "<crop>"                (no varieties)
    #   variety        -> "<crop>.<variety>"      (varieties, no strains)
    #   variety_strain -> "<crop>.<variety>.<strain>"
    # The catalog guarantees nodes exist at each level for the crop; a
    # block must specify exactly to this depth. No "none" sentinels.
    classification_depth: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'crop_only'")
    )


class CropVariety(Base, TimestampedMixin):
    __tablename__ = "crop_varieties"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    crop_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.crops.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Canonical hierarchical code: "<crop.code>.<variety.code>". Stable
    # (codes are immutable) and the cross-consumer targeting key.
    path: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Variety-level overrides. ``default_thresholds`` shallow-merges
    # over the crop's ``default_thresholds`` (variety wins per key).
    # ``phenology_stages_override``, when non-null, replaces the crop's
    # ``phenology_stages`` wholesale — the array is too irregular to
    # merge keywise.
    default_thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    phenology_stages_override: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    size_classes_override: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class CropVarietyStrain(Base, TimestampedMixin):
    """Within-variety selection (e.g. Mango → Alphonso → Short Alphonso).

    The third and deepest level of the crop taxonomy. Mirrors
    ``CropVariety``'s override columns one level down: a strain's
    ``default_thresholds`` shallow-merge over the *resolved* variety
    thresholds (strain wins per key), extending the crop → variety →
    strain override chain in ``crop_thresholds.resolve``.
    """

    __tablename__ = "crop_variety_strains"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    crop_variety_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.crop_varieties.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Canonical path: "<crop.code>.<variety.code>.<strain.code>".
    path: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    default_thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    phenology_stages_override: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    size_classes_override: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class CropAttributeDefinition(Base, TimestampedMixin):
    """Platform-curated typed field on the crop → block assignment.

    Attaches at any level of the taxonomy (``crop_id`` always set; plus
    ``crop_variety_id`` and/or ``crop_variety_strain_id`` for deeper rows) and
    resolves **deepest-wins by ``code``** — see
    ``app.modules.farms.crop_attributes.resolve_definitions``. A deeper row
    with the same ``code`` replaces the inherited one wholesale (unlike
    ``default_thresholds``, which shallow-merges): narrowing a range or an
    option list only reads correctly if the whole definition is replaced.

    ``show_when`` / ``required_when`` are one-level, non-recursive gates —
    ``{"code": <other definition code>, "in": [...]}`` against another
    attribute on the same assignment. Deliberately not a general expression
    language; the decision-tree evaluator is the place for those.
    """

    __tablename__ = "crop_attribute_definitions"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    crop_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.crops.id", ondelete="RESTRICT"),
        nullable=False,
    )
    crop_variety_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.crop_varieties.id", ondelete="RESTRICT"),
        nullable=True,
    )
    crop_variety_strain_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("public.crop_variety_strains.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Canonical path of the attachment node ("mango", "mango.sukkary",
    # "mango.alphonso.short"). Denormalised so the resolve is a prefix match.
    path: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str] = mapped_column(Text, nullable=False)
    description_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(Text, nullable=False)
    unit_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    decimal_places: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_max_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ``[{"code", "name_en", "name_ar", "sort_order"}, ...]`` for select types.
    #
    # ``none_as_null=True`` on all three JSONB columns, deliberately. By
    # default SQLAlchemy serialises Python ``None`` into JSON ``null`` rather
    # than SQL NULL, so an absent value would be stored as ``'null'::jsonb``
    # — which ``IS NOT NULL`` reports as present. That breaks the
    # ``options`` CHECK (a text attribute would look like it carries options)
    # and would make any future "has a gate" query wrong.
    options: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    required_when: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    show_when: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    group_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_reportable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class Farm(Base, TimestampedMixin):
    """Tenant-schema table; resolved via search_path."""

    __tablename__ = "farms"
    # No schema — search_path picks tenant_<id>.

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    boundary: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    # No SRID in the type: the zone is per farm, held by `utm_srid` below.
    boundary_utm: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", spatial_index=False),
        nullable=False,
    )
    # The UTM zone this farm's metric geometry lives in. Derived once from the
    # boundary centroid by the `farms_geom_compute` trigger and never
    # recomputed, because a change here moves `aoi_hash` and orphans imagery.
    utm_srid: Mapped[int] = mapped_column(Integer, nullable=False)
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    elevation_m: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    # Logical cross-schema ref to public.countries.code (no DB FK; validated in
    # the service). Drives Decision-Tree country targeting; blocks inherit it.
    country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    governorate: Mapped[str | None] = mapped_column(Text, nullable=True)
    district: Mapped[str | None] = mapped_column(Text, nullable=True)
    nearest_city: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    farm_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'commercial'")
    )
    ownership_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_water_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    established_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    # Lifecycle: `is_active` is derived from `active_from <= current_date
    # AND (active_to IS NULL OR active_to > current_date)`. See
    # tenant migration 0026.
    active_from: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("current_date")
    )
    active_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Farm-block config model PR-1 (tenant migration 0027): Shared-bucket
    # templates + per-category locks. Inert until PR-2/PR-3 wire them up.
    # (The Farm-only "manager" pointer farm_manager_id was dropped in U-4a /
    # tenant migration 0045 — the farm manager is now derived read-only from
    # the FarmManager farm-scope. See FarmResponse.farm_manager.)
    default_irrigation_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_irrigation_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_flow_rate_m3_per_hour: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    default_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    subscriptions_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    irrigation_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    org_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))

    # Grid category (tenant migration 0053). NULL on either value column
    # means "no template set" — Apply is a no-op, not an overwrite with
    # NULL. Not a resolution tier: copy-on-apply into grid_configs.
    default_grid_cell_size_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    default_anomaly_z_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), nullable=True
    )
    grid_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))

    # Field category (tenant migration 0081). How many days a field flag's pin
    # keeps drawing on the map. Read at raise time and STORED on the flag, so
    # editing this moves future pins only — changing it must not silently
    # remove hundreds of pins that are already out there.
    default_field_flag_pin_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    field_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )


class Block(Base, TimestampedMixin):
    __tablename__ = "blocks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    boundary: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=False,
    )
    # No SRID in the type: a block takes its farm's zone (see Farm.utm_srid).
    boundary_utm: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", spatial_index=False),
        nullable=False,
    )
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    elevation_m: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    slope_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    aspect_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    irrigation_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    irrigation_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    flow_rate_m3_per_hour: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    soil_texture: Mapped[str | None] = mapped_column(Text, nullable=True)
    salinity_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    soil_ph: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    soil_ec_ds_per_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    soil_organic_matter_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    last_soil_test_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # U-4b: per-block agronomist referenced by membership (cross-schema
    # logical ref to public.tenant_memberships, no FK — like the U-3 worker
    # link). Repointed from the raw users.id column in tenant migration 0046.
    agronomist_membership_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # Lifecycle: see Farm.active_from / active_to.
    active_from: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=text("current_date")
    )
    active_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    aoi_hash: Mapped[str] = mapped_column(Text, nullable=False)

    # Land-unit polymorphism (PR-1 of FarmDM rollout). A Block can be a
    # plain block (irregular polygon), a pivot (full-circle, center-pivot
    # irrigation), or a pivot_sector (pie-slice subdivision of a pivot).
    # parent_unit_id is required for pivot_sector and forbidden for the
    # other two — enforced by the migration's check constraint.
    unit_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'block'"))
    parent_unit_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="RESTRICT"),
        nullable=True,
    )
    irrigation_geometry: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class FarmImageryTemplate(Base):
    """Farm-level imagery subscription template.

    Multi-row per ``(farm_id, product_id)`` — what blocks should
    inherit when Apply is invoked. Distinct from
    ``farm_imagery_overrides`` (single-row resolver knobs from PR #65).
    See tenant migration 0028.
    """

    __tablename__ = "farm_imagery_template"

    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Logical cross-schema FK to public.imagery_products.id.
    product_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    cadence_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    cloud_cover_max_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class FarmWeatherTemplate(Base):
    """Farm-level weather subscription template. See ``FarmImageryTemplate``."""

    __tablename__ = "farm_weather_template"

    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Logical cross-schema FK to public.weather_providers.code.
    provider_code: Mapped[str] = mapped_column(Text, primary_key=True)
    cadence_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class BlockResponsibleLog(Base):
    """Append-only history of `blocks.agronomist_membership_id`.

    The column itself names one person and remembers nothing, which stopped
    being adequate once dispatch began defaulting to it: "why did this task go
    to them" is only answerable if the previous answers were kept.

    No `TimestampedMixin` — a history row is a fact about a moment, so it has
    `changed_at`/`changed_by` and is never updated or soft-deleted. Correcting
    a mistake means recording the correction as its own row.
    """

    __tablename__ = "block_responsible_log"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL on the first assignment; NULL on the new side means unassigned,
    # which is a change worth recording rather than an absence of one.
    previous_membership_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    new_membership_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    changed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class BlockCrop(Base, TimestampedMixin):
    __tablename__ = "block_crops"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    crop_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    crop_variety_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    # Deepest taxonomy node assigned (logical cross-schema ref to
    # public.crop_variety_strains). Set only for variety_strain crops.
    crop_variety_strain_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    # Denormalized canonical path ("<crop>[.<variety>[.<strain>]]") at the
    # crop's classification depth — the cross-consumer targeting key.
    crop_path: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    season_label: Mapped[str] = mapped_column(Text, nullable=False)
    # Valid time (tenant 0058): the period this assignment governs, half-open
    # `[from, to)`. `effective_to IS NULL` means ongoing — a perennial orchard
    # has no end until it is grubbed up. Distinct from the agronomic dates
    # below: planting and harvest are events, this is the record's validity,
    # and for a perennial the harvest is not the end of occupancy.
    #
    # `is_current` is now DERIVED from this range on read (see
    # `farms.validity.is_active_on`); the stored column is kept in step on
    # write for the partial unique index and any consumer not yet migrated.
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    planting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_harvest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Canopy size pick from the crop's resolved ``size_classes`` lookup; a
    # block-source field for the recommendation engine (small -> SAVI path).
    canopy_size_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    growth_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    growth_stage_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When true, the phenology auto-advance task skips this block (a manual
    # growth_stage stays authoritative).
    growth_stage_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'planned'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class BlockCropAttributeValue(Base, TimestampedMixin):
    """One crop-attribute value on one crop → block assignment.

    Typed columns rather than a JSONB blob: the report column picker and the
    decision-tree evaluator both *compare* these, and JSONB would force a CAST
    on every comparison — the failure family behind #331/#332/#335. Exactly
    one ``value_*`` column is non-null, enforced by a CHECK in tenant
    migration 0055.

    ``definition_id`` / ``definition_code`` are logical cross-schema refs to
    ``public.crop_attribute_definitions`` (no DB FK — same arrangement as
    ``block_crops.crop_id``). The code is denormalised because every consumer
    keys by code, and because it keeps history readable after a definition is
    retired.
    """

    __tablename__ = "block_crop_attribute_values"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_crop_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("block_crops.id", ondelete="CASCADE"),
        nullable=False,
    )
    definition_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    definition_code: Mapped[str] = mapped_column(Text, nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_option: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_options: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)


class BlockCropAttributeValueLog(Base):
    """Append-only history of one attribute's value on one assignment.

    Written by the service in the same transaction as the value write — a DB
    trigger has no access to the acting user. Carries both the previous and
    the new value so a row is self-describing, and distinguishes
    ``cleared_by_gate`` from a user clearing a field: "who deleted the
    transplant date?" has an answer when the real cause was someone switching
    the establishment method back to Seed.

    This is also what lets a report resolve a value **as of the period end**
    rather than silently back-dating today's number onto a Q1 report.
    """

    __tablename__ = "block_crop_attribute_value_log"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_crop_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("block_crops.id", ondelete="CASCADE"),
        nullable=False,
    )
    definition_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    definition_code: Mapped[str] = mapped_column(Text, nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_option: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_options: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    prev_value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    prev_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_value_boolean: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    prev_value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    prev_value_option: Mapped[str | None] = mapped_column(Text, nullable=True)
    prev_value_options: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # set | updated | cleared | cleared_by_gate
    change_kind: Mapped[str] = mapped_column(Text, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    changed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class GrowthStageLog(Base, TimestampedMixin):
    """Append-only history of phenology transitions for a block.

    `block_crops.growth_stage` carries the *current* stage; this table
    carries the timeline. Every transition lands here — manual entries
    from the UI, derivations from the GDD model (P2), and bulk imports.
    """

    __tablename__ = "growth_stage_logs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    block_crop_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("block_crops.id", ondelete="CASCADE"),
        nullable=True,
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'"))
    confirmed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    transition_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FarmAttachment(Base, TimestampedMixin):
    __tablename__ = "farm_attachments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    farm_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("farms.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    geo_point: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )


class BlockAttachment(Base, TimestampedMixin):
    __tablename__ = "block_attachments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    geo_point: Mapped[Any | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
