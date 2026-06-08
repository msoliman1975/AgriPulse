"""Seed the NDMI index into the imagery catalog (KB P2 prerequisite).

NDMI (Normalized Difference Moisture Index, NIR/SWIR1) is the
leaf/canopy-moisture index the knowledge-base water-stress catalog
depends on — distinct from the existing McFeeters ``ndwi`` (Green/NIR),
which tracks open surface water rather than tissue moisture. The SWIR1
band is already fetched for s2_l2a (see indices/computation.py band
order), so no provider/evalscript change is needed.

Adds one ``public.indices_catalog`` row and appends ``ndmi`` to the
s2_l2a product's index list. Both are idempotent. New scenes compute
NDMI going forward; backfilling historical aggregates is optional and
out of scope here.

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | Sequence[str] | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO public.indices_catalog (
            code, name_en, name_ar, formula_text,
            value_min, value_max, physical_meaning, is_standard
        )
        VALUES (
            'ndmi',
            $tag$Normalized Difference Moisture Index$tag$,
            $tag$مؤشر الرطوبة المعياري$tag$,
            $tag$(NIR - SWIR1) / (NIR + SWIR1)$tag$,
            -1.0,
            1.0,
            $tag$Leaf / canopy water content (equivalent to NDII). Falls as tissue dries — an early water-stress signal, distinct from NDWI (surface water).$tag$,
            TRUE
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    # Keep the s2_l2a product's advertised index list in sync.
    op.execute(
        """
        UPDATE public.imagery_products
           SET bands = array_append(bands, 'ndmi')
         WHERE code = 's2_l2a'
           AND provider_id = (
               SELECT id FROM public.imagery_providers WHERE code = 'sentinel_hub'
           )
           AND NOT ('ndmi' = ANY(bands))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE public.imagery_products
           SET bands = array_remove(bands, 'ndmi')
         WHERE code = 's2_l2a'
           AND provider_id = (
               SELECT id FROM public.imagery_providers WHERE code = 'sentinel_hub'
           )
        """
    )
    op.execute("DELETE FROM public.indices_catalog WHERE code = 'ndmi'")
