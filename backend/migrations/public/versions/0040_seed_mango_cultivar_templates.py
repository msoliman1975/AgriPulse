"""Seed per-cultivar mango plan templates (Egypt) + archive the demonstrator.

Replaces the thin 5-activity ``mango-season-eg`` demonstrator (0035, archived
here) with a stage-anchored agronomic blueprint applied to each of the six
commercial Egyptian cultivars. All cultivars share the same operation set;
timing differs automatically because each cultivar resolves its own phenology
windows at apply time (Keitt carries a late-season override from 0033).

Evidence tier per activity is flagged in the note:
  * [EG-FAO]   FAO "Fertilizer use by crop in Egypt" mango >10yr 360 N / 70
               P2O5 / 115 K2O kg/ha (≈151 / 29 / 48 kg/feddan) — verified 3-0.
  * [EG]       Egyptian field trial (powdery-mildew fungicides, 15-day) — verified.
  * [GENERIC]  not Egypt-calibrated (PBZ dose India/Thai; some pesticides) —
               calibrate locally / verify current MALR registration.

See docs/proposals/plan-templates-scientific-seed.md §1, §4.5.
Idempotent: each template skips if its code already exists.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text as SAText

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# code -> (name_en, crop_path, season_note)
_CULTIVARS = {
    "mango-keitt-eg": ("Mango — Keitt (Egypt)", "mango.keitt", "Late-season (harvest Sep-Oct)."),
    "mango-zebda-eg": ("Mango — Zebda (Egypt)", "mango.zebda", "Mid-season; large local canopy."),
    "mango-sukkary-eg": (
        "Mango — Sukkary (Egypt)",
        "mango.sukkary",
        "Mid-season; large local canopy.",
    ),
    "mango-alphonso-eg": ("Mango — Alphonso (Egypt)", "mango.alphonso", "Mid-season."),
    "mango-yasmina-eg": ("Mango — Yasmina (Egypt)", "mango.yasmina", "Mid-season."),
    "mango-crimson-eg": (
        "Mango — Crimson (Egypt)",
        "mango.crimson",
        "Mid/late-season; coloured export type.",
    ),
}

# (activity_type, stage_code, offset, duration, product, dosage, notes, sort)
# All anchor='stage'. N/P/K splits reference the verified FAO Egypt annual total.
_ACTIVITIES = [
    (
        "soil_prep",
        "post_harvest_flush",
        0,
        3,
        "Farmyard manure",
        "20-30 m3/feddan",
        "Post-harvest land prep + basin maintenance; incorporate organic manure. [GENERIC] calibrate to soil test.",
        1,
    ),
    (
        "fertilizing",
        "post_harvest_flush",
        7,
        1,
        "Urea (46% N)",
        "N split 1 of 3 (~50 kg/feddan)",
        "Post-harvest N flush to rebuild canopy reserves. Annual N 360 kg/ha = 151 kg/feddan. [EG-FAO]",
        2,
    ),
    (
        "spraying",
        "post_harvest_flush",
        14,
        1,
        "Zinc sulphate + chelated Fe + boron",
        "ZnSO4 0.3-0.5%, Fe-EDDHA per label, boric acid 0.1%",
        "Foliar micronutrients for calcareous/sandy reclaimed soils (lime-induced Zn/Fe deficiency). [EG]",
        3,
    ),
    (
        "pruning",
        "post_harvest_flush",
        21,
        3,
        None,
        None,
        "Post-harvest pruning: remove dead/criss-cross wood, open the canopy.",
        4,
    ),
    (
        "growth_regulator",
        "pre_flowering",
        0,
        1,
        "Paclobutrazol (PBZ)",
        "1.0-1.5 g a.i. per metre of canopy diameter, soil drench",
        "Flowering induction (inhibits gibberellin). Multi-year carryover; cultivar/soil dependent. [GENERIC] dose India/Thai, not Egypt-calibrated.",
        5,
    ),
    (
        "irrigation",
        "pre_flowering",
        14,
        30,
        None,
        None,
        "Withhold / reduce irrigation to induce flowering (deliberate water stress). Resume at flowering.",
        6,
    ),
    (
        "spraying",
        "pre_flowering",
        25,
        1,
        "Penconazole (TOPAS 10% EC)",
        "25-50 ml / 100 L water; 15-day interval",
        "Powdery mildew (Oidium mangiferae) at panicle emergence. Rotate with copper (COBOX) / carbendazim (KEMAZED). [EG] 4-season Dakahlia/Damietta trial.",
        7,
    ),
    (
        "fertilizing",
        "flowering",
        0,
        1,
        "Calcium superphosphate + potassium sulphate",
        "Full P2O5 (29 kg/feddan) + K split 1",
        "Pre-bloom P + K. Annual P2O5 70 kg/ha, K2O 115 kg/ha (48 kg/feddan). [EG-FAO]",
        8,
    ),
    (
        "spraying",
        "flowering",
        7,
        1,
        "Imidacloprid / lambda-cyhalothrin",
        "per label",
        "Mango leafhopper (hopper) at flowering. [GENERIC] verify current MALR registration.",
        9,
    ),
    (
        "observation",
        "fruit_set",
        0,
        1,
        None,
        None,
        "Scout fruit set, malformation and mealybug.",
        10,
    ),
    (
        "thinning",
        "fruit_set",
        14,
        2,
        None,
        None,
        "Fruit thinning: remove malformed/excess fruitlets to improve size. Cultivar-dependent.",
        11,
    ),
    (
        "irrigation",
        "fruit_development",
        0,
        60,
        None,
        None,
        "Regular irrigation through sizing; keep even moisture to avoid fruit drop.",
        12,
    ),
    (
        "fertilizing",
        "fruit_development",
        0,
        1,
        "NPK 12-12-17 + potassium sulphate",
        "N split 2 of 3 + K split 2",
        "Fruit-development fertigation for sizing. [EG-FAO] annual totals.",
        13,
    ),
    (
        "spraying",
        "fruit_development",
        10,
        1,
        "Spinosad bait (GF-120) + copper/azoxystrobin",
        "bait per label; fungicide per label",
        "Fruit fly (Bactrocera/Ceratitis) protein bait + anthracnose. [GENERIC] verify MALR registration.",
        14,
    ),
    (
        "harvesting",
        "fruit_development",
        60,
        14,
        None,
        None,
        "Harvest at physiological maturity (cultivar-timed; Keitt Sep-Oct, mid-season Jun-Aug).",
        15,
    ),
    (
        "fertilizing",
        "post_harvest_flush",
        0,
        1,
        "Ammonium nitrate (33.5% N)",
        "N split 3 of 3",
        "Recovery N after harvest. [EG-FAO]",
        16,
    ),
]


def _seed_template(bind, code, name, crop_path, crop_id, descr):
    existing = bind.execute(
        text("SELECT id FROM public.plan_templates WHERE code = :c"), {"c": code}
    ).scalar()
    if existing is not None:
        return
    tid = bind.execute(
        text(
            "INSERT INTO public.plan_templates "
            "(code, name, crop_path, crop_id, country, region, description, status) "
            "VALUES (:code, :name, :cp, :crop_id, 'EG', NULL, :descr, 'published') RETURNING id"
        ),
        {"code": code, "name": name, "cp": crop_path, "crop_id": crop_id, "descr": descr},
    ).scalar_one()
    for atype, stage, off, dur, product, dosage, notes, sort in _ACTIVITIES:
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
        text("SELECT id FROM public.crops WHERE code = 'mango' AND deleted_at IS NULL")
    ).scalar()
    base = (
        "Stage-anchored season plan for Egyptian mango. Fertiliser totals from "
        "FAO 'Fertilizer use by crop in Egypt' (>10-yr trees); flowering, "
        "fruit-development and post-harvest tasks anchor to phenology stages. "
    )
    for code, (name, crop_path, season_note) in _CULTIVARS.items():
        _seed_template(bind, code, name, crop_path, crop_id, base + season_note)

    # Archive the thin demonstrator in favour of the per-cultivar templates.
    bind.execute(
        text(
            "UPDATE public.plan_templates SET status = 'archived' " "WHERE code = 'mango-season-eg'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    codes = list(_CULTIVARS.keys())
    bind.execute(
        text("DELETE FROM public.plan_templates WHERE code = ANY(:codes)").bindparams(
            bindparam("codes", type_=ARRAY(SAText))
        ),
        {"codes": codes},
    )
    bind.execute(
        text(
            "UPDATE public.plan_templates SET status = 'published' "
            "WHERE code = 'mango-season-eg'"
        )
    )
