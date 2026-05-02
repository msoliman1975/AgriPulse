"""Indices ORM models. Catalog in `public`; per-block aggregates in the
per-tenant schema as a TimescaleDB hypertable. data_model § 7.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db.base import UUID_V7_DEFAULT, Base, TimestampedMixin


class IndicesCatalog(Base, TimestampedMixin):
    """`public.indices_catalog` — definitions of supported indices."""

    __tablename__ = "indices_catalog"
    __table_args__ = {"schema": "public"}

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=UUID_V7_DEFAULT
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name_en: Mapped[str] = mapped_column(Text, nullable=False)
    name_ar: Mapped[str | None] = mapped_column(Text, nullable=True)
    formula_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_min: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    value_max: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    physical_meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_standard: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("TRUE"))


class BlockIndexAggregate(Base):
    """`tenant_<id>.block_index_aggregates` — TimescaleDB hypertable.

    No PK column: a hypertable's true unique constraint must include
    the time partitioning column. The composite UNIQUE on
    (time, block_id, index_code, product_id) is the per-scene
    idempotency key — re-running indices computation is a no-op.

    `valid_pixel_pct` is a stored generated column (TimescaleDB ≥ 2.11).
    SQLAlchemy `Computed(persisted=True)` mirrors that on the model side
    so write paths don't accidentally try to set it.
    """

    __tablename__ = "block_index_aggregates"
    # tuple form: (constraints..., dict-of-options). The dict at the end
    # is intentional — SQLAlchemy reads it for `__table_args__["schema"]`
    # and similar; we leave it empty (tenant schema resolves via
    # search_path).
    __table_args__: tuple[UniqueConstraint | dict[str, object], ...] = (
        UniqueConstraint(
            "time",
            "block_id",
            "index_code",
            "product_id",
            name="uq_block_index_aggregates_time_block_index_product",
        ),
        {},
    )

    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    block_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)
    index_code: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, primary_key=True
    )

    mean: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    min: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    max: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    p10: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    p50: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    p90: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
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
