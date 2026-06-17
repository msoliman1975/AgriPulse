"""Seed per-cultivar date-palm plan templates (Egypt).

Stage-anchored to the date-palm phenology seeded in 0038 (dry cultivars
Siwi/Medjool carry the late-ripening override from 0039). Each of the seven
cultivars shares the operation blueprint; they differ in the harvest stage
(soft/early cultivars at Khalal, semi-dry at Rutab, dry at Tamar) and the
pollination method.

Egypt-verified anchors (3-vote): Zaghloul Mariut NPK program (1000 g N/palm
in 4 splits, 750 g K2O/palm in 3 splits, 1.5 kg superphosphate, 25-30 kg
manure, ammonium sulphate best on calcareous); Zaghloul pollination
suspension; Hayany 6-strand pollination; Oligonychus acaricides 8 wk
post-pollination; FAO red-palm-weevil monitoring windows; Barhi/Hayani/
Samany/Zaghloul harvested at Khalal; ripening-stage durations.

Flags: [EG] Egypt-verified · [GENERIC] verify current MALR registration.
See docs/proposals/plan-templates-scientific-seed.md §1, §4.5.
Idempotent: each template skips if its code already exists.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text as SAText

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOFT_POLLEN = (
    "Soft-cultivar suspension: 4 g pollen + 2 ml treacle + 2 g ascorbic acid "
    "+ 1 g boric acid per L water (Zaghloul-verified)"
)
_SEMIDRY_POLLEN = "~6 pollen strands per inflorescence (Hayany-verified optimum)"
_DRY_POLLEN = "Traditional dry pollen strands (best for Barhi/Medjool per cultivar trials)"

# code -> (name, crop_path, harvest_stage, pollen_note, extra_descr)
_CULTIVARS = {
    "datepalm-zaghloul-eg": (
        "Date palm — Zaghloul (Egypt)",
        "date_palm.zaghloul",
        "khalal",
        _SOFT_POLLEN,
        "Soft; harvested at Khalal.",
    ),
    "datepalm-samany-eg": (
        "Date palm — Samany (Egypt)",
        "date_palm.samany",
        "khalal",
        _SOFT_POLLEN,
        "Soft; 3 pollinations each followed by bagging; harvested ~2nd week September at colour peak.",
    ),
    "datepalm-hayany-eg": (
        "Date palm — Hayany (Egypt)",
        "date_palm.hayany",
        "khalal",
        _SEMIDRY_POLLEN,
        "Semi-dry; consumed at Khalal/Rutab.",
    ),
    "datepalm-amhat-eg": (
        "Date palm — Amhat (Egypt)",
        "date_palm.amhat",
        "rutab",
        _SEMIDRY_POLLEN,
        "Semi-dry; harvested at Rutab.",
    ),
    "datepalm-siwi-eg": (
        "Date palm — Siwi (Egypt)",
        "date_palm.siwi",
        "tamar",
        _DRY_POLLEN,
        "Dry; late-ripening, cured at Tamar. Siwa Oasis Siwi NPK (Ibrahim 2013): 1.2-1.5 kg N / 0.044-0.065 kg P / 0.25-0.42 kg K per palm.",
    ),
    "datepalm-barhi-eg": (
        "Date palm — Barhi (Egypt)",
        "date_palm.barhi",
        "khalal",
        _DRY_POLLEN,
        "Famous fresh-Khalal cultivar.",
    ),
    "datepalm-medjool-eg": (
        "Date palm — Medjool (Egypt)",
        "date_palm.medjool",
        "tamar",
        _DRY_POLLEN,
        "Premium dry; cured at Tamar.",
    ),
}

# Base blueprint (harvest row appended per cultivar).
# (activity_type, stage_code, offset, duration, product, dosage, notes, sort)
_BASE = [
    (
        "pruning",
        "dormancy",
        0,
        5,
        None,
        None,
        "Winter pruning + dethorning + remove old fronds/offshoots before pollination.",
        1,
    ),
    (
        "fertilizing",
        "dormancy",
        30,
        1,
        "Cattle manure + calcium superphosphate",
        "25-30 kg manure/palm + 1.5 kg superphosphate/palm",
        "Single winter organic + P application. [EG] Zaghloul Mariut program.",
        2,
    ),
    (
        "fertilizing",
        "pollination",
        0,
        1,
        "Ammonium sulphate + potassium sulphate (48% K2O)",
        "N split 1 of 4 + K split 1 of 3 (annual ~1000 g N/palm, 750 g K2O/palm)",
        "Ammonium sulphate best on calcareous soils. [EG] Zaghloul Mariut.",
        3,
    ),
    # pollination row injected per cultivar at sort 4
    (
        "fertilizing",
        "fruit_set",
        0,
        1,
        "Ammonium sulphate",
        "N split 2 of 4",
        "[EG] Zaghloul Mariut program.",
        5,
    ),
    (
        "thinning",
        "fruit_set",
        14,
        3,
        None,
        None,
        "Bunch & strand thinning: remove excess strands/whole bunches to balance load and size.",
        6,
    ),
    (
        "fertilizing",
        "kimri",
        0,
        1,
        "Ammonium sulphate + potassium sulphate",
        "N split 3 of 4 + K split 2 of 3",
        "[EG] Zaghloul Mariut program.",
        7,
    ),
    (
        "spraying",
        "kimri",
        14,
        1,
        "Vertimec 1.8% EC (abamectin) / Challenger Super 24% SC",
        "Vertimec 40 ml/100 L or Challenger Super 60 ml/100 L",
        "Old World date mite (Oligonychus/Boufaroua) ~8 weeks after pollination. [EG] New Valley trial.",
        8,
    ),
    (
        "bagging",
        "kimri",
        21,
        5,
        None,
        None,
        "Cover/bag bunches (dust, birds, lesser date moth) and bend bunches for exposure.",
        9,
    ),
    (
        "spraying",
        "kimri",
        0,
        1,
        "Registered insecticide (verify MALR)",
        "per label",
        "Lesser date moth (Batrachedra) at early fruit. [GENERIC] no Egypt-verified active found.",
        10,
    ),
    (
        "fertilizing",
        "kimri",
        45,
        1,
        "Ammonium sulphate + potassium sulphate",
        "N split 4 of 4 + K split 3 of 3",
        "Final N/K splits. [EG] Zaghloul Mariut program.",
        11,
    ),
    (
        "irrigation",
        "kimri",
        0,
        90,
        None,
        None,
        "Peak summer water demand through Kimri/Khalal; reduce pre-harvest dry-down for dry cultivars.",
        12,
    ),
    (
        "observation",
        "khalal",
        0,
        1,
        None,
        None,
        "Scout ripening + service red palm weevil pheromone traps (peaks Apr-Jun & Sep-Nov; "
        "1-4 traps/ha, every 7-15 days). [EG] FAO.",
        13,
    ),
]

_HARVEST_NOTE = {
    "khalal": "Harvest at Khalal (firm, coloured) — soft/early Egyptian cultivars. [EG] verified.",
    "rutab": "Harvest at Rutab (soft ripe).",
    "tamar": "Harvest at Tamar (fully cured) after pre-harvest dry-down — dry cultivars. [EG].",
}


def _seed_template(bind, code, name, crop_path, crop_id, harvest_stage, pollen_note, descr):
    if (
        bind.execute(
            text("SELECT id FROM public.plan_templates WHERE code = :c"), {"c": code}
        ).scalar()
        is not None
    ):
        return
    tid = bind.execute(
        text(
            "INSERT INTO public.plan_templates "
            "(code, name, crop_path, crop_id, country, region, description, status) "
            "VALUES (:code, :name, :cp, :crop_id, 'EG', NULL, :descr, 'published') RETURNING id"
        ),
        {"code": code, "name": name, "cp": crop_path, "crop_id": crop_id, "descr": descr},
    ).scalar_one()

    activities = list(_BASE)
    activities.append(
        (
            "pollination",
            "pollination",
            0,
            3,
            "Fresh pollen",
            pollen_note,
            "Manual pollination 2 days after spathe cracking, afternoon. [EG] Zaghloul recipe; method cultivar-dependent.",
            4,
        )
    )
    activities.append(
        (
            "harvesting",
            harvest_stage,
            0,
            14,
            None,
            None,
            _HARVEST_NOTE[harvest_stage],
            14,
        )
    )

    for atype, stage, off, dur, product, dosage, notes, sort in activities:
        bind.execute(
            text(
                "INSERT INTO public.plan_template_activities "
                "(template_id, activity_type, anchor, milestone_id, stage_code, "
                " offset_days, duration_days, product_name, dosage, notes, sort_order) "
                "VALUES (:tid, :atype, 'stage', NULL, :stage, :off, :dur, :product, :dosage, :notes, :sort)"
            ),
            {
                "tid": tid,
                "atype": atype,
                "stage": stage,
                "off": off,
                "dur": dur,
                "product": product,
                "dosage": dosage,
                "notes": notes,
                "sort": sort,
            },
        )


def upgrade() -> None:
    bind = op.get_bind()
    crop_id = bind.execute(
        text("SELECT id FROM public.crops WHERE code = 'date_palm' AND deleted_at IS NULL")
    ).scalar()
    base = (
        "Stage-anchored annual plan for Egyptian date palm. Fertiliser program "
        "from the Zaghloul Mariut study (calcareous reclaimed soil); pollination, "
        "thinning, bagging and mite control anchor to phenology stages. "
    )
    for code, (name, crop_path, harvest_stage, pollen_note, extra) in _CULTIVARS.items():
        _seed_template(
            bind, code, name, crop_path, crop_id, harvest_stage, pollen_note, base + extra
        )


def downgrade() -> None:
    op.get_bind().execute(
        text("DELETE FROM public.plan_templates WHERE code = ANY(:codes)").bindparams(
            bindparam("codes", type_=ARRAY(SAText))
        ),
        {"codes": list(_CULTIVARS.keys())},
    )
