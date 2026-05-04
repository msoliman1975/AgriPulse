"""Seed sentinel_hub provider, Sentinel-2 L2A product, six standard indices.

Per data_model § 6.2 / § 6.3 / § 7.2 plus the prompt's "in scope" list:
the MVP knows exactly one provider (sentinel_hub), one product (s2_l2a),
and six standard indices (NDVI, NDWI, EVI, SAVI, NDRE, GNDVI). Custom /
non-standard indices land in a later prompt — they go in the same
catalog with `is_standard = false`.

The seeds are idempotent — re-running upgrade leaves identical rows.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-01
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- Sentinel Hub provider ---------------------------------------------------
# `config_schema` documents what an `imagery_providers.config` JSONB blob is
# expected to contain. We don't validate against it in MVP (FastAPI at the
# API edge does that for incoming bodies); it lives here so platform admins
# editing the catalog have machine-readable guidance.
_SENTINEL_HUB_CONFIG_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["oauth_url", "catalog_url", "process_url"],
    "properties": {
        "oauth_url": {"type": "string", "format": "uri"},
        "catalog_url": {"type": "string", "format": "uri"},
        "process_url": {"type": "string", "format": "uri"},
    },
    "additionalProperties": False,
}


# --- Six standard indices ----------------------------------------------------
# Bounds match the typical normalized-difference range. The aggregator may
# observe slightly out-of-range values for edge cases (saturated bands,
# extreme atmospheric correction artefacts); the catalog bounds drive the
# UI's chart axes, not a hard physical clamp.
_INDICES: tuple[dict[str, object], ...] = (
    {
        "code": "ndvi",
        "name_en": "Normalized Difference Vegetation Index",
        "name_ar": "مؤشر الغطاء النباتي المعياري",
        "formula_text": "(NIR - Red) / (NIR + Red)",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Greenness / chlorophyll density. Higher = denser canopy. "
            "Saturates above ~0.85 in dense crops."
        ),
    },
    {
        "code": "ndwi",
        "name_en": "Normalized Difference Water Index",
        "name_ar": "مؤشر المياه المعياري",
        "formula_text": "(Green - NIR) / (Green + NIR)",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Surface water content / canopy moisture. Positive values "
            "track open water and high leaf water content."
        ),
    },
    {
        "code": "evi",
        "name_en": "Enhanced Vegetation Index",
        "name_ar": "مؤشر الغطاء النباتي المحسّن",
        "formula_text": "2.5 * (NIR - Red) / (NIR + 6 * Red - 7.5 * Blue + 1)",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Like NDVI but corrects for soil and atmospheric noise; "
            "preferred over NDVI in dense canopies where NDVI saturates."
        ),
    },
    {
        "code": "savi",
        "name_en": "Soil-Adjusted Vegetation Index",
        "name_ar": "مؤشر الغطاء النباتي المعدّل للتربة",
        "formula_text": "1.5 * (NIR - Red) / (NIR + Red + 0.5)",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Vegetation index with a soil-brightness correction; better "
            "than NDVI in sparse / early-season cover."
        ),
    },
    {
        "code": "ndre",
        "name_en": "Normalized Difference Red Edge",
        "name_ar": "مؤشر الحافة الحمراء المعياري",
        "formula_text": "(NIR - RedEdge) / (NIR + RedEdge)",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Chlorophyll content via the red-edge band; sensitive to "
            "nitrogen status earlier than NDVI."
        ),
    },
    {
        "code": "gndvi",
        "name_en": "Green Normalized Difference Vegetation Index",
        "name_ar": "مؤشر الغطاء النباتي الأخضر المعياري",
        "formula_text": "(NIR - Green) / (NIR + Green)",
        "value_min": -1.0,
        "value_max": 1.0,
        "physical_meaning": (
            "Greenness via the green band instead of red; useful for "
            "mid-to-late-season canopy when NDVI saturates."
        ),
    },
)


def upgrade() -> None:
    # All seeds are ON CONFLICT-safe: every catalog table has a UNIQUE on
    # `code` (the indices_catalog and imagery_providers tables) or on
    # (provider_id, code) (imagery_products), so re-running the migration
    # is a no-op once the rows exist.

    op.execute(
        f"""
        INSERT INTO public.imagery_providers (code, name, kind, config_schema)
        VALUES (
            'sentinel_hub',
            'Sentinel Hub',
            'commercial_api',
            '{json.dumps(_SENTINEL_HUB_CONFIG_SCHEMA)}'::jsonb
        )
        ON CONFLICT (code) DO NOTHING
        """
    )

    # Sentinel-2 L2A: bottom-of-atmosphere reflectance, the workhorse
    # product for vegetation indices. Bands listed in the order the
    # `SentinelHubProvider` will request them in PR-B.
    op.execute(
        """
        INSERT INTO public.imagery_products (
            provider_id, code, name, resolution_m, revisit_days_avg,
            bands, supported_indices, cost_tier
        )
        SELECT
            (SELECT id FROM public.imagery_providers WHERE code = 'sentinel_hub'),
            's2_l2a',
            'Sentinel-2 L2A',
            10.00,
            5.00,
            ARRAY['blue','green','red','red_edge_1','nir','swir1','swir2']::text[],
            ARRAY['ndvi','ndwi','evi','savi','ndre','gndvi']::text[],
            'medium'
        ON CONFLICT (provider_id, code) DO NOTHING
        """
    )

    for entry in _INDICES:
        op.execute(
            f"""
            INSERT INTO public.indices_catalog (
                code, name_en, name_ar, formula_text,
                value_min, value_max, physical_meaning, is_standard
            )
            VALUES (
                '{entry["code"]}',
                $tag${entry["name_en"]}$tag$,
                $tag${entry["name_ar"]}$tag$,
                $tag${entry["formula_text"]}$tag$,
                {entry["value_min"]},
                {entry["value_max"]},
                $tag${entry["physical_meaning"]}$tag$,
                TRUE
            )
            ON CONFLICT (code) DO NOTHING
            """
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM public.indices_catalog WHERE code IN "
        "('ndvi','ndwi','evi','savi','ndre','gndvi')"
    )
    op.execute(
        "DELETE FROM public.imagery_products "
        "WHERE code = 's2_l2a' AND provider_id = "
        "(SELECT id FROM public.imagery_providers WHERE code = 'sentinel_hub')"
    )
    op.execute("DELETE FROM public.imagery_providers WHERE code = 'sentinel_hub'")
