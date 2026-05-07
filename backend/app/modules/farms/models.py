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
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


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
    boundary_utm: Mapped[Any] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=32636, spatial_index=False),
        nullable=False,
    )
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    area_m2: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    elevation_m: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
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
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))


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
    boundary_utm: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=32636, spatial_index=False),
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
    responsible_user_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
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
    season_label: Mapped[str] = mapped_column(Text, nullable=False)
    planting_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_harvest_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_harvest_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_harvest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    plant_density_per_ha: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    row_spacing_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    plant_spacing_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    growth_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    growth_stage_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("FALSE"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'planned'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


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
