"""Seed phenology stages + size classes for mango (perennial) and potato (annual).

Both crops already exist (migration 0006); mango was set to
``classification_depth='variety_strain'`` with a worked alphonso/eswwy
example in 0030. This migration leaves that depth + those rows untouched and:
  * gives mango crop-level ``phenology_stages`` (calendar_doy windows for
    Egypt) + ``size_classes`` (small/medium/large) and extends
    ``relevant_indices`` with the indices the mango ruleset uses
    (ndre, ndmi, savi). Crop-level phenology resolves for every mango block
    regardless of variety/strain depth;
  * seeds the 5 commercial Egyptian mango varieties (keitt, yasmina,
    sukkary, zebda, crimson) alongside the existing example varieties, with
    a Keitt phenology override (late-season) and a large-tree size override
    for the local sukkary/zebda;
  * gives potato ``phenology_stages`` (days_from_planting) as the annual
    exemplar for the auto-advance task.

Stage windows are sensible operational defaults (editable via the catalog),
not calibrated study values. Idempotent: re-running upserts the same rows.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _stage(code: str, en: str, ar: str, order: int, start: str, end: str) -> dict:
    return {
        "code": code,
        "name_en": en,
        "name_ar": ar,
        "order": order,
        "advance": {"mode": "calendar_doy", "start_doy": start, "end_doy": end},
    }


# Crop-level mango cycle (generic mid-season Egyptian mango). Non-overlapping,
# covers all 12 months so the auto-advance task always resolves a stage.
_MANGO_STAGES = {
    "stages": [
        _stage(
            "pre_flowering",
            "Pre-flowering (stress induction)",
            "ما قبل التزهير (التصويم)",
            1,
            "12-01",
            "01-31",
        ),
        _stage("flowering", "Flowering", "التزهير", 2, "02-01", "03-15"),
        _stage("fruit_set", "Fruit set", "العقد", 3, "03-16", "04-30"),
        _stage("fruit_development", "Fruit development", "تطور الثمار", 4, "05-01", "07-15"),
        _stage("post_harvest_flush", "Post-harvest flush", "النمو بعد الحصاد", 5, "07-16", "10-31"),
        _stage("veg_flush", "Vegetative flush", "النمو الخضري", 6, "11-01", "11-30"),
    ]
}

# Keitt is a late-season variety (harvest Sep-Oct) -> shifted windows.
_KEITT_STAGES = {
    "stages": [
        _stage(
            "pre_flowering",
            "Pre-flowering (stress induction)",
            "ما قبل التزهير (التصويم)",
            1,
            "12-15",
            "02-15",
        ),
        _stage("flowering", "Flowering", "التزهير", 2, "02-16", "03-31"),
        _stage("fruit_set", "Fruit set", "العقد", 3, "04-01", "05-15"),
        _stage("fruit_development", "Fruit development", "تطور الثمار", 4, "05-16", "09-15"),
        _stage("post_harvest_flush", "Post-harvest flush", "النمو بعد الحصاد", 5, "09-16", "11-30"),
        _stage("veg_flush", "Vegetative flush", "النمو الخضري", 6, "12-01", "12-14"),
    ]
}

_MANGO_SIZE_CLASSES = {
    "classes": [
        {"code": "small", "name_en": "Small (<2 m)", "name_ar": "صغير (<2 م)", "order": 1},
        {"code": "medium", "name_en": "Medium (2-4 m)", "name_ar": "متوسط (2-4 م)", "order": 2},
        {"code": "large", "name_en": "Large (>4 m)", "name_ar": "كبير (>4 م)", "order": 3},
    ]
}

# Local big-canopy varieties skip the smallest class.
_LOCAL_LARGE_SIZE_CLASSES = {
    "classes": [
        {"code": "medium", "name_en": "Medium (2-4 m)", "name_ar": "متوسط (2-4 م)", "order": 1},
        {"code": "large", "name_en": "Large (4-6 m)", "name_ar": "كبير (4-6 م)", "order": 2},
        {"code": "very_large", "name_en": "Very large (>6 m)", "name_ar": "ضخم (>6 م)", "order": 3},
    ]
}

# code -> (name_en, name_ar, phenology_override, size_override)
_MANGO_VARIETIES = {
    "keitt": ("Keitt", "كيت", _KEITT_STAGES, None),
    "yasmina": ("Yasmina", "ياسمينا", None, None),
    "sukkary": ("Sukkary", "سكري", None, _LOCAL_LARGE_SIZE_CLASSES),
    "zebda": ("Zebda", "زبدية", None, _LOCAL_LARGE_SIZE_CLASSES),
    "crimson": ("Crimson", "كريمسون", None, None),
}


def _days_stage(code: str, en: str, ar: str, order: int, start: int, end: int) -> dict:
    return {
        "code": code,
        "name_en": en,
        "name_ar": ar,
        "order": order,
        "advance": {"mode": "days_from_planting", "start_day": start, "end_day": end},
    }


_POTATO_STAGES = {
    "stages": [
        _days_stage("emergence", "Emergence", "الإنبات", 1, 0, 20),
        _days_stage("vegetative", "Vegetative", "النمو الخضري", 2, 20, 45),
        _days_stage("tuber_initiation", "Tuber initiation", "بداية التدرين", 3, 45, 65),
        _days_stage("tuber_bulking", "Tuber bulking", "امتلاء الدرنات", 4, 65, 100),
        _days_stage("maturation", "Maturation", "النضج", 5, 100, 120),
    ]
}


def upgrade() -> None:
    bind = op.get_bind()

    # --- Mango crop-level update (depth left as set by 0030) -----------
    bind.execute(
        text(
            "UPDATE public.crops SET "
            " phenology_stages = CAST(:stages AS jsonb), "
            " size_classes = CAST(:sizes AS jsonb), "
            " relevant_indices = :indices "
            "WHERE code = 'mango'"
        ).bindparams(bindparam("indices", type_=ARRAY(Text))),
        {
            "stages": json.dumps(_MANGO_STAGES),
            "sizes": json.dumps(_MANGO_SIZE_CLASSES),
            "indices": ["ndvi", "ndre", "ndmi", "savi"],
        },
    )

    crop_id = bind.execute(text("SELECT id FROM public.crops WHERE code = 'mango'")).scalar_one()

    insert_variety = text(
        "INSERT INTO public.crop_varieties "
        "(crop_id, code, name_en, name_ar, path, "
        " phenology_stages_override, size_classes_override) "
        "VALUES (:crop_id, :code, :name_en, :name_ar, :path, "
        "        CAST(:pheno AS jsonb), CAST(:sizes AS jsonb)) "
        "ON CONFLICT DO NOTHING"
    )
    for code, (name_en, name_ar, pheno, sizes) in _MANGO_VARIETIES.items():
        bind.execute(
            insert_variety,
            {
                "crop_id": crop_id,
                "code": code,
                "name_en": name_en,
                "name_ar": name_ar,
                "path": f"mango.{code}",
                "pheno": json.dumps(pheno) if pheno is not None else None,
                "sizes": json.dumps(sizes) if sizes is not None else None,
            },
        )

    # --- Potato (annual exemplar) -------------------------------------
    bind.execute(
        text(
            "UPDATE public.crops SET phenology_stages = CAST(:stages AS jsonb) "
            "WHERE code = 'potato'"
        ),
        {"stages": json.dumps(_POTATO_STAGES)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Only the 5 varieties this migration added — leave the 0030 example
    # rows (alphonso/eswwy + strains) and mango's depth untouched.
    paths = [f"mango.{code}" for code in _MANGO_VARIETIES]
    bind.execute(
        text("DELETE FROM public.crop_varieties WHERE path = ANY(:paths)").bindparams(
            bindparam("paths", type_=ARRAY(Text))
        ),
        {"paths": paths},
    )
    bind.execute(
        text(
            "UPDATE public.crops SET "
            " phenology_stages = NULL, size_classes = NULL, "
            " relevant_indices = :indices "
            "WHERE code = 'mango'"
        ).bindparams(bindparam("indices", type_=ARRAY(Text))),
        {"indices": ["ndvi", "ndwi"]},
    )
    bind.execute(text("UPDATE public.crops SET phenology_stages = NULL WHERE code = 'potato'"))
