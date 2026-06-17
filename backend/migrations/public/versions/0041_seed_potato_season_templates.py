"""Seed Egyptian potato plan templates — one per growing season.

Potato phenology is ``days_from_planting`` (season start = block planting
date), so the same stage-anchored blueprint serves all three Egyptian
seasons; only the planting window and pest emphasis differ. Templates target
``crop_path = 'potato'`` so they apply to every potato block regardless of
cultivar (Spunta/Diamant/Cara/Lady Rosetta/Hermes differ mainly in
days-to-maturity, noted in the harvest row, not in the operation set).

Evidence flags in notes:
  * [EG]          Egypt-verified N split (curresweb MEJAR 2019, Menoufia) —
                  3 doses: ammonium sulphate after emergence, then ammonium
                  nitrate +2 wk & +4 wk.
  * [EG-FAO]      FAO "Fertilizer use by crop in Egypt" potato 300 N / 145
                  P2O5 / 115 K2O kg/ha (≈126 / 61 / 48 kg/feddan) — verified.
  * [GENERIC-HIST] seed rate 750 kg/feddan (Attalah 1980, historical).
  * [GENERIC]     pesticides — verify current MALR registration.

See docs/proposals/plan-templates-scientific-seed.md §1, §4.5.
Idempotent: each template skips if its code already exists.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text as SAText

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEASONS = {
    "potato-winter-eg": (
        "Potato — Winter / main (Egypt)",
        "Winter (main) season: plant Oct-Nov, harvest ~Feb. Highest late-blight "
        "pressure under cool humid conditions — tighten the fungicide interval.",
    ),
    "potato-summer-eg": (
        "Potato — Summer (Egypt)",
        "Summer season: plant Jan to mid-Mar, harvest May-Jun. Hotter, faster "
        "maturity; watch aphid/whitefly virus vectors.",
    ),
    "potato-nili-eg": (
        "Potato — Nili / autumn (Egypt)",
        "Nili (autumn/fall) season: plant Aug to mid-Oct, harvest Dec to mid-Feb. "
        "Heat at planting; potato tuber-moth pressure.",
    ),
}

# (activity_type, anchor, stage_code, offset, duration, product, dosage, notes, sort)
_ACTIVITIES = [
    (
        "soil_prep",
        "start",
        None,
        0,
        5,
        "Farmyard manure + calcium superphosphate + potassium sulphate",
        "manure 20 m3/feddan; full P2O5 61 kg/feddan + K split 1",
        "Land prep + ridging (70 cm) + base P & K. P2O5 145 / K2O 115 kg/ha (FAO Egypt). [EG-FAO]",
        1,
    ),
    (
        "planting",
        "start",
        None,
        5,
        3,
        "Certified seed tubers",
        "~750 kg/feddan (~1,800 kg/ha); 25 cm in-row, 70 cm ridges",
        "Planting. Seed rate historical (Attalah 1980) — calibrate to seed size. [GENERIC-HIST]",
        2,
    ),
    (
        "fertilizing",
        "stage",
        "emergence",
        0,
        1,
        "Ammonium sulphate (20.5% N)",
        "N split 1 of 3 (~42 kg/feddan); ~21 days after planting",
        "1st N dose after emergence as ammonium sulphate. Annual N 300 kg/ha = 126 kg/feddan. [EG]/[EG-FAO]",
        3,
    ),
    (
        "spraying",
        "stage",
        "emergence",
        7,
        1,
        "Imidacloprid / pymetrozine",
        "per label",
        "Aphid (PLRV/PVY vectors) + whitefly + tuber moth. [GENERIC] verify MALR registration.",
        4,
    ),
    (
        "irrigation",
        "stage",
        "emergence",
        0,
        90,
        None,
        None,
        "Regular irrigation; avoid moisture stress at tuber initiation/bulking, reduce near maturation.",
        5,
    ),
    (
        "fertilizing",
        "stage",
        "vegetative",
        0,
        1,
        "Ammonium nitrate (33.5% N)",
        "N split 2 of 3; ~2 weeks after split 1",
        "2nd N dose as ammonium nitrate. [EG] verified split.",
        6,
    ),
    (
        "hilling",
        "stage",
        "vegetative",
        7,
        2,
        None,
        None,
        "Earthing-up (~30-35 DAP): cover tubers, prevent greening, support stems.",
        7,
    ),
    (
        "spraying",
        "stage",
        "vegetative",
        0,
        1,
        "Mancozeb -> rotate Cymoxanil+Mancozeb / chlorothalonil; metalaxyl under pressure",
        "7-10 day intervals",
        "Late blight (Phytophthora) + early blight. Preventive before canopy closure; tighten under humidity. [GENERIC] verify MALR registration.",
        8,
    ),
    (
        "fertilizing",
        "stage",
        "tuber_initiation",
        0,
        1,
        "Ammonium nitrate + potassium sulphate",
        "N split 3 of 3 (~4 weeks after split 1) + remaining K2O",
        "Final N + K for bulking. [EG] verified split / [EG-FAO] totals.",
        9,
    ),
    (
        "observation",
        "stage",
        "tuber_bulking",
        0,
        1,
        None,
        None,
        "Scout late blight, tuber moth and tuber set.",
        10,
    ),
    (
        "spraying",
        "stage",
        "maturation",
        -10,
        1,
        "Haulm desiccant (registered) or mechanical flailing",
        "per label",
        "Haulm-kill ~10-14 days before harvest to set skin. [GENERIC] desiccant registration varies; mechanical flailing preferred.",
        11,
    ),
    (
        "harvesting",
        "stage",
        "maturation",
        0,
        7,
        None,
        None,
        "Harvest at skin-set (~90-120 days; Spunta earlier, Hermes/Lady Rosetta processing types later).",
        12,
    ),
]


def _seed_template(bind, code, name, crop_id, descr):
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
            "VALUES (:code, :name, 'potato', :crop_id, 'EG', NULL, :descr, 'published') RETURNING id"
        ),
        {"code": code, "name": name, "crop_id": crop_id, "descr": descr},
    ).scalar_one()
    for atype, anchor, stage, off, dur, product, dosage, notes, sort in _ACTIVITIES:
        bind.execute(
            text(
                "INSERT INTO public.plan_template_activities "
                "(template_id, activity_type, anchor, milestone_id, stage_code, "
                " offset_days, duration_days, product_name, dosage, notes, sort_order) "
                "VALUES (:tid, :atype, :anchor, NULL, :stage, :off, :dur, :product, :dosage, :notes, :sort)"
            ),
            {
                "tid": tid,
                "atype": atype,
                "anchor": anchor,
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
        text("SELECT id FROM public.crops WHERE code = 'potato' AND deleted_at IS NULL")
    ).scalar()
    for code, (name, descr) in _SEASONS.items():
        _seed_template(bind, code, name, crop_id, descr)


def downgrade() -> None:
    op.get_bind().execute(
        text("DELETE FROM public.plan_templates WHERE code = ANY(:codes)").bindparams(
            bindparam("codes", type_=ARRAY(SAText))
        ),
        {"codes": list(_SEASONS.keys())},
    )
