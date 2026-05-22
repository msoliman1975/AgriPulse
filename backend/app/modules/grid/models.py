"""Grid-zones ORM models. All three tables live in the per-tenant schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class GridConfig(Base, TimestampedMixin):
    """``tenant_<id>.grid_configs`` — one active row per (block, product).

    Soft-retire via ``retired_at`` instead of delete so old cells +
    observations stay queryable as history.
    """

    __tablename__ = "grid_configs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    block_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Cross-schema logical FK to public.imagery_products.id (same pattern
    # as imagery_aoi_subscriptions).
    product_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    cell_size_m: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    utm_srid: Mapped[int] = mapped_column(Integer, nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GridCell(Base):
    """``tenant_<id>.grid_cells`` — materialised polygons for one grid_config."""

    __tablename__ = "grid_cells"
    __table_args__: tuple[UniqueConstraint | CheckConstraint | dict[str, object], ...] = (
        UniqueConstraint(
            "grid_config_id",
            "row_idx",
            "col_idx",
            name="uq_grid_cells_grid_config_row_col",
        ),
        CheckConstraint("area_m2 > 0", name="ck_grid_cells_area_positive"),
        {},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    grid_config_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("grid_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    col_idx: Mapped[int] = mapped_column(Integer, nullable=False)
    # Geometry has no compile-time SRID — the parent config's utm_srid
    # is the source of truth. spatial_index is created by the migration
    # (GIST) so we disable the implicit one.
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POLYGON", spatial_index=False),
        nullable=False,
    )
    centroid: Mapped[Any] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    area_m2: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class BlockGridAggregate(Base):
    """``tenant_<id>.block_grid_aggregates`` — TimescaleDB hypertable.

    One row per (scene_time, cell, index, product). Mirrors
    :class:`BlockIndexAggregate` but at cell grain instead of block.
    No FK on ``cell_id`` because hypertables can't carry foreign keys;
    the service layer is the integrity boundary.
    """

    __tablename__ = "block_grid_aggregates"
    __table_args__: tuple[UniqueConstraint | CheckConstraint | dict[str, object], ...] = (
        UniqueConstraint(
            "time",
            "cell_id",
            "index_code",
            "product_id",
            name="uq_block_grid_aggregates_time_cell_index_product",
        ),
        CheckConstraint(
            "total_pixel_count >= 0 AND valid_pixel_count >= 0 "
            "AND valid_pixel_count <= total_pixel_count",
            name="ck_block_grid_aggregates_pixel_counts",
        ),
        {},
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    cell_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    block_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    index_code: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, primary_key=True
    )

    mean: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    min: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    max: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    std_dev: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)

    valid_pixel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pixel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_pixel_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        Computed(
            "100.0 * valid_pixel_count / NULLIF(total_pixel_count, 0)",
            persisted=True,
        ),
        nullable=True,
    )
    cloud_cover_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    stac_item_id: Mapped[str] = mapped_column(Text, nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
