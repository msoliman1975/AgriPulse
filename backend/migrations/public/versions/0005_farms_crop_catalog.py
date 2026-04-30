"""Crop catalog: public.crops, public.crop_varieties.

Per data_model § 5.2 / § 5.3. Curated by platform admins; tenants reference
these via the (logical) cross-schema FK from `tenant_<id>.block_crops`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- public.crops ---------------------------------------------------
    op.create_table(
        "crops",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("scientific_name", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("is_perennial", sa.Boolean(), nullable=False),
        sa.Column("default_growing_season_days", sa.Integer(), nullable=True),
        sa.Column("gdd_base_temp_c", sa.Numeric(4, 1), nullable=True),
        sa.Column("gdd_upper_temp_c", sa.Numeric(4, 1), nullable=True),
        sa.Column(
            "relevant_indices",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['ndvi']::text[]"),
        ),
        sa.Column("phenology_stages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_crops_code"),
        sa.CheckConstraint(
            "category IN ('cereal','fruit_tree','vegetable','fiber','fodder',"
            "'sugar','oilseed','legume','other')",
            name="ck_crops_category",
        ),
        sa.CheckConstraint(
            "default_growing_season_days IS NULL OR default_growing_season_days > 0",
            name="ck_crops_growing_season_positive",
        ),
        sa.CheckConstraint(
            "gdd_upper_temp_c IS NULL OR gdd_base_temp_c IS NULL "
            "OR gdd_upper_temp_c > gdd_base_temp_c",
            name="ck_crops_gdd_upper_above_base",
        ),
    )
    op.create_index(
        "ix_crops_category_active",
        "crops",
        ["category"],
        postgresql_where=sa.text("is_active = TRUE"),
    )
    op.execute(
        "CREATE TRIGGER trg_crops_updated_at "
        "BEFORE UPDATE ON public.crops "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    # ---- public.crop_varieties -----------------------------------------
    op.create_table(
        "crop_varieties",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column("crop_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["crop_id"],
            ["crops.id"],
            name="fk_crop_varieties_crop_id_crops",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("crop_id", "code", name="uq_crop_varieties_crop_id_code"),
    )
    op.execute(
        "CREATE TRIGGER trg_crop_varieties_updated_at "
        "BEFORE UPDATE ON public.crop_varieties "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_crop_varieties_updated_at ON public.crop_varieties")
    op.drop_table("crop_varieties")
    op.execute("DROP TRIGGER IF EXISTS trg_crops_updated_at ON public.crops")
    op.drop_index("ix_crops_category_active", table_name="crops")
    op.drop_table("crops")
