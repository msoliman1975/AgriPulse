"""Seed crop_varieties for potato and date palm (Egyptian cultivars).

Both crops are at ``classification_depth='variety'`` (set by 0030), so blocks
can already be assigned to a cultivar; this migration just supplies the
catalog rows so per-cultivar plan templates (crop_path ``potato.spunta`` /
``date_palm.zaghloul`` …) can target them.

Date-palm cultivars carry a phenology override only where the ripening
window differs materially from the crop-level default (dry cultivars such as
Siwi ripen ~6 weeks later). Potato cultivars share the crop-level
days_from_planting phenology (season start drives the calendar), so no
override. Idempotent via ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

revision: str = "0039"
down_revision: str | None = "0038"
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


# Dry cultivars (Siwi/Saidy) flower & ripen later; harvested fully cured at
# Tamar in Oct-Nov. Shifted ~6 wk vs the soft-cultivar crop default.
_DRY_STAGES = {
    "stages": [
        _stage(
            "dormancy", "Winter dormancy / pruning", "السكون الشتوي / التقليم", 1, "12-15", "03-15"
        ),
        _stage(
            "pollination",
            "Spathe emergence & pollination",
            "خروج الطلع والتلقيح",
            2,
            "03-16",
            "04-30",
        ),
        _stage("fruit_set", "Fruit set (Hababouk)", "العقد (الحبابوك)", 3, "05-01", "05-31"),
        _stage("kimri", "Kimri (green growth)", "الكمري (النمو الأخضر)", 4, "06-01", "08-31"),
        _stage("khalal", "Khalal (colour / sizing)", "الخلال (التلوين)", 5, "09-01", "09-30"),
        _stage("rutab", "Rutab (soft ripe)", "الرطب", 6, "10-01", "10-31"),
        _stage(
            "tamar", "Tamar (cured) / post-harvest", "التمر / ما بعد الحصاد", 7, "11-01", "12-14"
        ),
    ]
}

# code -> (name_en, name_ar, phenology_override)
_POTATO_VARIETIES = {
    "spunta": ("Spunta", "سبونتا", None),
    "diamant": ("Diamant", "ديامنت", None),
    "cara": ("Cara", "كارا", None),
    "lady_rosetta": ("Lady Rosetta", "ليدي روزيتا", None),
    "hermes": ("Hermes", "هيرمس", None),
}

_DATE_VARIETIES = {
    # Soft
    "zaghloul": ("Zaghloul", "زغلول", None),
    "samany": ("Samany", "سماني", None),
    # Semi-dry
    "hayany": ("Hayany", "حياني", None),
    "amhat": ("Amhat", "أمهات", None),
    # Dry / semi-dry (late ripening)
    "siwi": ("Siwi", "سيوي", _DRY_STAGES),
    "barhi": ("Barhi", "برحي", None),
    "medjool": ("Medjool", "مجدول", _DRY_STAGES),
}


def _seed(bind, crop_code: str, varieties: dict) -> None:
    crop_id = bind.execute(
        text("SELECT id FROM public.crops WHERE code = :c AND deleted_at IS NULL"),
        {"c": crop_code},
    ).scalar()
    if crop_id is None:
        return
    insert = text(
        "INSERT INTO public.crop_varieties "
        "(crop_id, code, name_en, name_ar, path, phenology_stages_override) "
        "VALUES (:crop_id, :code, :name_en, :name_ar, :path, CAST(:pheno AS jsonb)) "
        "ON CONFLICT DO NOTHING"
    )
    for code, (name_en, name_ar, pheno) in varieties.items():
        bind.execute(
            insert,
            {
                "crop_id": crop_id,
                "code": code,
                "name_en": name_en,
                "name_ar": name_ar,
                "path": f"{crop_code}.{code}",
                "pheno": json.dumps(pheno) if pheno is not None else None,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    _seed(bind, "potato", _POTATO_VARIETIES)
    _seed(bind, "date_palm", _DATE_VARIETIES)


def downgrade() -> None:
    bind = op.get_bind()
    paths = [f"potato.{c}" for c in _POTATO_VARIETIES] + [f"date_palm.{c}" for c in _DATE_VARIETIES]
    bind.execute(
        text("DELETE FROM public.crop_varieties WHERE path = ANY(:paths)").bindparams(
            bindparam("paths", type_=ARRAY(Text))
        ),
        {"paths": paths},
    )
