"""Crop taxonomy: Crop -> Variety -> Strain, per-crop classification depth,
hierarchical path codes.

Adds the third taxonomy level (``crop_variety_strains``), a per-crop
``classification_depth`` driving how deep a block assignment goes
(crop_only | variety | variety_strain), and a canonical ``path`` code
(``<crop>.<variety>[.<strain>]``) on varieties + strains used as the
cross-consumer targeting key (prefix-matchable). No "none" sentinels:
a crop_only crop's path is just ``<crop>``.

Seeds a worked example (Mango -> Alphonso/Eswwy -> Short/Long) so the
cascade + targeting are exercisable end to end.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEPTHS = ("crop_only", "variety", "variety_strain")


def upgrade() -> None:
    # 1. Per-crop classification depth.
    op.add_column(
        "crops",
        sa.Column(
            "classification_depth",
            sa.Text(),
            nullable=False,
            server_default="crop_only",
        ),
        schema="public",
    )
    op.create_check_constraint(
        "ck_crops_classification_depth",
        "crops",
        "classification_depth IN ('crop_only', 'variety', 'variety_strain')",
        schema="public",
    )

    # 2. Canonical path on varieties.
    op.add_column(
        "crop_varieties",
        sa.Column("path", sa.Text(), nullable=False, server_default=""),
        schema="public",
    )

    # 3. Strain table (mirrors crop_varieties one level down).
    op.create_table(
        "crop_variety_strains",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("public.uuid_generate_v7()"),
        ),
        sa.Column(
            "crop_variety_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.crop_varieties.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "attributes",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("default_thresholds", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("phenology_stages_override", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("crop_variety_id", "code", name="uq_strain_variety_code"),
        schema="public",
    )
    op.execute(
        "CREATE TRIGGER trg_crop_variety_strains_updated_at "
        "BEFORE UPDATE ON public.crop_variety_strains "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )
    op.create_index(
        "ix_crop_variety_strains_variety",
        "crop_variety_strains",
        ["crop_variety_id"],
        schema="public",
    )
    op.create_index(
        "ix_crop_variety_strains_path", "crop_variety_strains", ["path"], schema="public"
    )
    op.create_index("ix_crop_varieties_path", "crop_varieties", ["path"], schema="public")

    # 4. Backfill any existing variety paths (none today, but keep correct).
    op.execute(
        """
        UPDATE public.crop_varieties v
           SET path = c.code || '.' || v.code
          FROM public.crops c
         WHERE c.id = v.crop_id AND (v.path IS NULL OR v.path = '')
        """
    )
    # Crops that already have varieties are at least 'variety' deep.
    op.execute(
        """
        UPDATE public.crops
           SET classification_depth = 'variety'
         WHERE classification_depth = 'crop_only'
           AND id IN (SELECT DISTINCT crop_id FROM public.crop_varieties)
        """
    )

    # 5. Worked example: Mango -> {Alphonso, Eswwy} -> {Short, Long}.
    op.execute(
        """
        INSERT INTO public.crop_varieties (crop_id, code, name_en, name_ar, path)
        SELECT c.id, v.code, v.name_en, v.name_ar, 'mango.' || v.code
          FROM public.crops c
          CROSS JOIN (VALUES
              ('alphonso', 'Alphonso', 'الفونس'),
              ('eswwy', 'Eswwy', 'عويس')
          ) AS v(code, name_en, name_ar)
         WHERE c.code = 'mango'
           AND NOT EXISTS (
               SELECT 1 FROM public.crop_varieties x
                WHERE x.crop_id = c.id AND x.code = v.code
           )
        """
    )
    op.execute(
        """
        INSERT INTO public.crop_variety_strains (crop_variety_id, code, name_en, name_ar, path)
        SELECT v.id, s.code, s.name_en, NULL, v.path || '.' || s.code
          FROM public.crop_varieties v
          CROSS JOIN (VALUES ('short', 'Short'), ('long', 'Long')) AS s(code, name_en)
         WHERE v.path IN ('mango.alphonso', 'mango.eswwy')
           AND NOT EXISTS (
               SELECT 1 FROM public.crop_variety_strains x
                WHERE x.crop_variety_id = v.id AND x.code = s.code
           )
        """
    )
    op.execute(
        "UPDATE public.crops SET classification_depth = 'variety_strain' WHERE code = 'mango'"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_crop_variety_strains_updated_at ON public.crop_variety_strains"
    )
    op.drop_table("crop_variety_strains", schema="public")
    op.drop_index("ix_crop_varieties_path", table_name="crop_varieties", schema="public")
    op.execute(
        "DELETE FROM public.crop_varieties WHERE crop_id IN (SELECT id FROM public.crops WHERE code = 'mango')"
    )
    op.drop_column("crop_varieties", "path", schema="public")
    # The metadata naming convention (ck_%(table_name)s_%(constraint_name)s)
    # is applied at create time, so the upgrade's create_check_constraint
    # ("ck_crops_classification_depth") actually produced
    # "ck_crops_ck_crops_classification_depth". drop_constraint does NOT
    # re-apply the convention, so drop by the real name; IF EXISTS keeps the
    # session-shared migration-roundtrip tests resilient.
    op.execute(
        "ALTER TABLE public.crops "
        "DROP CONSTRAINT IF EXISTS ck_crops_ck_crops_classification_depth"
    )
    op.drop_column("crops", "classification_depth", schema="public")
