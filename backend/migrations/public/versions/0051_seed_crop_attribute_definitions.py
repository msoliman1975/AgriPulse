"""Seed the establishment / planting-material attribute groups.

Migration 0050 built the mechanism; this fills it. Five crops, chosen because
between them they show that the *concept* transfers while the *attributes*
do not:

``mango`` / ``citrus_orange`` / ``citrus_mandarin``
    Established as a grafted or transplanted nursery tree. Needs the
    transplant date, the age and size of the tree at transplant, and the
    rootstock — and the rootstock options are crop-specific (a mango goes on
    a polyembryonic seedling, a citrus on sour orange or Volkamer lemon).

``date_palm``
    Never grafted. Establishes from an offshoot or a tissue-culture
    plantlet, so the whole field set is different: offshoot age and weight,
    mother-palm reference, TC lab and batch.

``potato``
    Not a tree at all, but the same shape of question: what planting material,
    which grade, which generation, what lot, sprouted or not.

``tomato``
    Transplanted like a tree, but from a nursery tray: seedling age in days,
    true-leaf count, tray cell count, and a rootstock *cultivar* for grafted
    seedlings.

Three levels are exercised deliberately, so the deepest-wins resolver is
covered by real data rather than only by tests:

* crop level for everything above;
* **variety** level — ``mango.sukkary`` and ``mango.zebda`` are propagated
  locally on their own seedling rootstock, so their ``rootstock_type`` option
  list is narrowed;
* **strain** level — ``mango.alphonso.short`` nursery trees are supplied under
  2.5 m, so ``transplant_height_cm`` narrows from 0–2000 to 0–250.

Idempotent: ``ON CONFLICT (path, code) DO NOTHING``. Rows whose crop /
variety / strain is absent from the catalog are skipped by the join rather
than failing the migration — the mango strains only exist where migration
0030 seeded them.

Revision ID: 0051
Revises: 0050
Create Date: 2026-08-05
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | Sequence[str] | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _opt(code: str, en: str, ar: str, order: int) -> dict[str, Any]:
    return {"code": code, "name_en": en, "name_ar": ar, "sort_order": order}


def _gate(code: str, values: list[str]) -> dict[str, Any]:
    return {"code": code, "in": values}


# Groups. `group_code` sections the assignment form; the bilingual names ride
# on every definition so the form needs no second lookup to render a heading.
_ESTABLISHMENT = ("establishment", "Establishment", "التأسيس")
_PLANTING_MATERIAL = ("planting_material", "Planting material", "مادة الزراعة")
_NURSERY = ("nursery", "Nursery & transplant", "المشتل والشتل")


# ---- mango ----------------------------------------------------------------

_MANGO_METHODS = [
    _opt("seed", "Seed", "بذرة", 1),
    _opt("seedling", "Seedling", "شتلة", 2),
    _opt("transplanted_tree", "Transplanted tree", "شجرة منقولة", 3),
    _opt("grafted_tree", "Grafted tree", "شجرة مطعمة", 4),
    _opt("rootstock", "Rootstock only", "أصل فقط", 5),
    _opt("cutting", "Cutting", "عقلة", 6),
    _opt("tissue_culture", "Tissue culture", "زراعة أنسجة", 7),
]
_MANGO_TRANSPLANTED = ["transplanted_tree", "grafted_tree", "rootstock"]
_MANGO_GRAFTED = ["grafted_tree", "rootstock"]
_MANGO_ROOTSTOCKS = [
    _opt("local_polyembryonic", "Local polyembryonic seedling", "بذري بلدي متعدد الأجنة", 1),
    _opt("sukkary_seedling", "Sukkary seedling", "بذري سكري", 2),
    _opt("zebda_seedling", "Zebda seedling", "بذري زبدية", 3),
    _opt("13_1", "13-1", "13-1", 4),
]

# ---- citrus ---------------------------------------------------------------

_CITRUS_METHODS = [
    _opt("seedling", "Seedling", "شتلة", 1),
    _opt("transplanted_tree", "Transplanted tree", "شجرة منقولة", 2),
    _opt("grafted_tree", "Grafted tree", "شجرة مطعمة", 3),
]
_CITRUS_TRANSPLANTED = ["transplanted_tree", "grafted_tree"]
_CITRUS_ROOTSTOCKS = [
    _opt("sour_orange", "Sour orange", "نارنج", 1),
    _opt("volkamer_lemon", "Volkamer lemon", "فولكامريانا", 2),
    _opt("carrizo_citrange", "Carrizo citrange", "كاريزو سيترانج", 3),
    _opt("cleopatra_mandarin", "Cleopatra mandarin", "كليوباترا", 4),
]


def _tree_establishment(
    *,
    methods: list[dict[str, Any]],
    transplanted: list[str],
    grafted: list[str],
    rootstocks: list[dict[str, Any]],
    max_age_months: int,
) -> list[dict[str, Any]]:
    """The establishment group shared by mango and the two citrus crops."""
    return [
        {
            "code": "establishment_method",
            "name_en": "Establishment method",
            "name_ar": "طريقة التأسيس",
            "description_en": (
                "How this block was established. Determines which of the " "fields below apply."
            ),
            "description_ar": "كيف تم تأسيس هذه القطعة. يحدد أي الحقول التالية تنطبق.",
            "value_type": "single_select",
            "options": methods,
            "is_required": True,
            "sort_order": 1,
        },
        {
            "code": "transplant_date",
            "name_en": "Transplant date",
            "name_ar": "تاريخ الشتل",
            "description_en": (
                "When the young tree went into this block — distinct from the "
                "planting date, which anchors the season."
            ),
            "description_ar": (
                "تاريخ نقل الشجرة الصغيرة إلى القطعة — يختلف عن تاريخ الزراعة " "الذي يحدد الموسم."
            ),
            "value_type": "date",
            "sort_order": 2,
            "show_when": _gate("establishment_method", transplanted),
            "required_when": _gate("establishment_method", transplanted),
        },
        {
            "code": "age_at_transplant_months",
            "name_en": "Age at transplant",
            "name_ar": "عمر الشجرة عند الشتل",
            # The staleness caveat is in the help text on purpose: v1 has no
            # derived type, so this number does not age by itself.
            "description_en": (
                "Nursery age of the tree on the transplant date. This value "
                "does not update on its own — edit it when it changes."
            ),
            "description_ar": (
                "عمر الشجرة في المشتل عند تاريخ الشتل. لا تتحدث هذه القيمة "
                "تلقائيًا — عدّلها عند تغيّرها."
            ),
            "value_type": "integer",
            "unit_en": "months",
            "unit_ar": "شهر",
            "value_min": 0,
            "value_max": max_age_months,
            "sort_order": 3,
            "show_when": _gate("establishment_method", transplanted),
            "required_when": _gate("establishment_method", transplanted),
        },
        {
            "code": "transplant_height_cm",
            "name_en": "Height at transplant",
            "name_ar": "ارتفاع الشجرة عند الشتل",
            "value_type": "decimal",
            "unit_en": "cm",
            "unit_ar": "سم",
            "value_min": 0,
            "value_max": 2000,
            "decimal_places": 1,
            "sort_order": 4,
            "show_when": _gate("establishment_method", transplanted),
        },
        {
            "code": "transplant_trunk_diameter_cm",
            "name_en": "Trunk diameter at transplant",
            "name_ar": "قطر الساق عند الشتل",
            "value_type": "decimal",
            "unit_en": "cm",
            "unit_ar": "سم",
            "value_min": 0,
            "value_max": 500,
            "decimal_places": 1,
            "sort_order": 5,
            "show_when": _gate("establishment_method", transplanted),
            "is_reportable": False,
        },
        {
            "code": "rootstock_type",
            "name_en": "Rootstock",
            "name_ar": "الأصل",
            "value_type": "single_select",
            "options": rootstocks,
            "sort_order": 6,
            "show_when": _gate("establishment_method", grafted),
            "required_when": _gate("establishment_method", grafted),
        },
        {
            "code": "nursery_source",
            "name_en": "Nursery / supplier",
            "name_ar": "المشتل / المورد",
            "value_type": "text",
            "text_max_length": 120,
            "sort_order": 8,
            "show_when": _gate(
                "establishment_method",
                [m["code"] for m in methods if m["code"] != "seed"],
            ),
            "is_reportable": False,
        },
    ]


_MANGO_CROP = _tree_establishment(
    methods=_MANGO_METHODS,
    transplanted=_MANGO_TRANSPLANTED,
    grafted=_MANGO_GRAFTED,
    rootstocks=_MANGO_ROOTSTOCKS,
    max_age_months=600,
) + [
    {
        "code": "graft_union_height_cm",
        "name_en": "Graft union height",
        "name_ar": "ارتفاع منطقة التطعيم",
        "value_type": "decimal",
        "unit_en": "cm",
        "unit_ar": "سم",
        "value_min": 0,
        "value_max": 200,
        "decimal_places": 1,
        "sort_order": 7,
        "show_when": _gate("establishment_method", ["grafted_tree"]),
        "is_reportable": False,
    },
]

_CITRUS_CROP = _tree_establishment(
    methods=_CITRUS_METHODS,
    transplanted=_CITRUS_TRANSPLANTED,
    grafted=["grafted_tree"],
    rootstocks=_CITRUS_ROOTSTOCKS,
    max_age_months=360,
)


# Variety-level narrowing: Sukkary and Zebda are propagated locally on their
# own seedling rootstock, so the generic four-option list is wrong for them.
# Replaces the inherited definition wholesale (deepest-wins).
def _local_rootstock(seedling_code: str, en: str, ar: str) -> dict[str, Any]:
    return {
        "code": "rootstock_type",
        "name_en": "Rootstock",
        "name_ar": "الأصل",
        "description_en": (
            f"{en} is propagated locally on its own seedling rootstock; the "
            "generic list is narrowed here."
        ),
        "description_ar": f"يُكاثر {ar} محليًا على أصله البذري؛ القائمة العامة مختصرة هنا.",
        "value_type": "single_select",
        "options": [
            _opt(seedling_code, f"{en} seedling", f"بذري {ar}", 1),
            _opt(
                "local_polyembryonic",
                "Local polyembryonic seedling",
                "بذري بلدي متعدد الأجنة",
                2,
            ),
        ],
        "sort_order": 6,
        "show_when": _gate("establishment_method", _MANGO_GRAFTED),
        "required_when": _gate("establishment_method", _MANGO_GRAFTED),
    }


# ---- date palm ------------------------------------------------------------

_DATE_PALM_CROP: list[dict[str, Any]] = [
    {
        "code": "propagation_source",
        "name_en": "Propagation source",
        "name_ar": "مصدر الإكثار",
        "description_en": (
            "Date palm is not grafted — it establishes from an offshoot or " "from tissue culture."
        ),
        "description_ar": "لا يُطعَّم النخيل — يُؤسَّس من الفسائل أو من زراعة الأنسجة.",
        "value_type": "single_select",
        "options": [
            _opt("offshoot", "Offshoot", "فسيلة", 1),
            _opt("tissue_culture", "Tissue culture", "زراعة أنسجة", 2),
            _opt("seedling", "Seedling (from seed)", "بذري", 3),
        ],
        "is_required": True,
        "sort_order": 1,
    },
    {
        "code": "offshoot_age_months",
        "name_en": "Offshoot age at planting",
        "name_ar": "عمر الفسيلة عند الزراعة",
        "value_type": "integer",
        "unit_en": "months",
        "unit_ar": "شهر",
        "value_min": 12,
        "value_max": 120,
        "sort_order": 2,
        "show_when": _gate("propagation_source", ["offshoot"]),
        "required_when": _gate("propagation_source", ["offshoot"]),
    },
    {
        "code": "offshoot_weight_kg",
        "name_en": "Offshoot weight",
        "name_ar": "وزن الفسيلة",
        "value_type": "decimal",
        "unit_en": "kg",
        "unit_ar": "كجم",
        "value_min": 5,
        "value_max": 60,
        "decimal_places": 1,
        "sort_order": 3,
        "show_when": _gate("propagation_source", ["offshoot"]),
    },
    {
        "code": "mother_palm_ref",
        "name_en": "Mother palm reference",
        "name_ar": "مرجع النخلة الأم",
        "value_type": "text",
        "text_max_length": 60,
        "sort_order": 4,
        "show_when": _gate("propagation_source", ["offshoot"]),
        "is_reportable": False,
    },
    {
        "code": "tc_lab_source",
        "name_en": "Tissue-culture lab",
        "name_ar": "معمل زراعة الأنسجة",
        "value_type": "text",
        "text_max_length": 120,
        "sort_order": 5,
        "show_when": _gate("propagation_source", ["tissue_culture"]),
        "required_when": _gate("propagation_source", ["tissue_culture"]),
    },
    {
        "code": "tc_batch_code",
        "name_en": "TC batch code",
        "name_ar": "كود تشغيلة الأنسجة",
        "value_type": "text",
        "text_max_length": 40,
        "sort_order": 6,
        "show_when": _gate("propagation_source", ["tissue_culture"]),
        "is_reportable": False,
    },
]


# ---- potato ---------------------------------------------------------------

_POTATO_TUBERS = ["certified_seed_tuber", "farm_saved_tuber"]

_POTATO_CROP: list[dict[str, Any]] = [
    {
        "code": "seed_material",
        "name_en": "Seed material",
        "name_ar": "مادة التقاوي",
        "value_type": "single_select",
        "options": [
            _opt("certified_seed_tuber", "Certified seed tuber", "تقاوي درنية معتمدة", 1),
            _opt("farm_saved_tuber", "Farm-saved tuber", "تقاوي من المزرعة", 2),
            _opt("minituber", "Minituber", "درنة صغيرة", 3),
            _opt("true_potato_seed", "True potato seed", "بذرة حقيقية", 4),
        ],
        "is_required": True,
        "sort_order": 1,
    },
    {
        "code": "seed_tuber_grade",
        "name_en": "Seed tuber grade",
        "name_ar": "رتبة التقاوي",
        "value_type": "single_select",
        "options": [
            _opt("28_35", "28–35 mm", "28–35 مم", 1),
            _opt("35_45", "35–45 mm", "35–45 مم", 2),
            _opt("45_55", "45–55 mm", "45–55 مم", 3),
            _opt("55_65", "55–65 mm", "55–65 مم", 4),
        ],
        "sort_order": 2,
        "show_when": _gate("seed_material", _POTATO_TUBERS),
        # Required only for certified seed: a farm-saved lot often has no
        # graded size, and demanding one would block the save.
        "required_when": _gate("seed_material", ["certified_seed_tuber"]),
    },
    {
        "code": "seed_generation",
        "name_en": "Seed generation",
        "name_ar": "جيل التقاوي",
        "value_type": "single_select",
        "options": [
            _opt("E", "Elite", "نخبة", 1),
            _opt("G1", "G1", "ج1", 2),
            _opt("G2", "G2", "ج2", 3),
            _opt("G3", "G3", "ج3", 4),
            _opt("G4", "G4", "ج4", 5),
        ],
        "sort_order": 3,
        "show_when": _gate("seed_material", ["certified_seed_tuber"]),
    },
    {
        "code": "seed_lot_code",
        "name_en": "Seed lot code",
        "name_ar": "كود تشغيلة التقاوي",
        "value_type": "text",
        "text_max_length": 40,
        "sort_order": 4,
        "show_when": _gate("seed_material", ["certified_seed_tuber"]),
        "is_reportable": False,
    },
    {
        "code": "sprouting_status",
        "name_en": "Sprouting status at planting",
        "name_ar": "حالة التزريع عند الزراعة",
        "value_type": "single_select",
        "options": [
            _opt("dormant", "Dormant", "ساكنة", 1),
            _opt("sprouted_1_3", "Sprouted 1–3 mm", "مزرعة 1–3 مم", 2),
            _opt("sprouted_over_3", "Sprouted > 3 mm", "مزرعة أكثر من 3 مم", 3),
            _opt("pre_sprouted", "Pre-sprouted in trays", "تزريع مسبق في صواني", 4),
        ],
        "sort_order": 5,
    },
    {
        "code": "seed_treatment",
        "name_en": "Seed treatment",
        "name_ar": "معاملة التقاوي",
        "description_en": (
            "Multi-select. In a decision tree this is comparable with `in` " "and `eq` only."
        ),
        "description_ar": "اختيار متعدد. يُقارن في شجرة القرار بـ in و eq فقط.",
        "value_type": "multi_select",
        "options": [
            _opt("fungicide_dust", "Fungicide dust", "مطهر فطري بودرة", 1),
            _opt("insecticide", "Insecticide", "مبيد حشري", 2),
            _opt("sprout_inhibitor", "Sprout inhibitor", "مثبط تزريع", 3),
            _opt("none", "None", "بدون", 4),
        ],
        "sort_order": 6,
    },
]


# ---- tomato ---------------------------------------------------------------

_TOMATO_TRANSPLANTED = ["nursery_seedling", "grafted_seedling"]

_TOMATO_CROP: list[dict[str, Any]] = [
    {
        "code": "planting_material",
        "name_en": "Planting material",
        "name_ar": "مادة الزراعة",
        "description_en": (
            "Same transplant concept as a fruit tree — and an entirely " "different set of fields."
        ),
        "description_ar": "نفس مفهوم الشتل في أشجار الفاكهة — لكن بحقول مختلفة تمامًا.",
        "value_type": "single_select",
        "options": [
            _opt("direct_seed", "Direct seed", "بذر مباشر", 1),
            _opt("nursery_seedling", "Nursery seedling", "شتلة مشتل", 2),
            _opt("grafted_seedling", "Grafted seedling", "شتلة مطعمة", 3),
        ],
        "is_required": True,
        "sort_order": 1,
    },
    {
        "code": "seedling_age_days",
        "name_en": "Seedling age at transplant",
        "name_ar": "عمر الشتلة عند الشتل",
        "value_type": "integer",
        "unit_en": "days",
        "unit_ar": "يوم",
        "value_min": 14,
        "value_max": 60,
        "sort_order": 2,
        "show_when": _gate("planting_material", _TOMATO_TRANSPLANTED),
        "required_when": _gate("planting_material", _TOMATO_TRANSPLANTED),
    },
    {
        "code": "true_leaves_at_transplant",
        "name_en": "True leaves at transplant",
        "name_ar": "عدد الأوراق الحقيقية عند الشتل",
        "value_type": "integer",
        "value_min": 2,
        "value_max": 10,
        "sort_order": 3,
        "show_when": _gate("planting_material", _TOMATO_TRANSPLANTED),
    },
    {
        "code": "tray_cell_count",
        "name_en": "Nursery tray",
        "name_ar": "صينية المشتل",
        "value_type": "single_select",
        "options": [
            _opt("209", "209-cell", "209 عين", 1),
            _opt("104", "104-cell", "104 عين", 2),
            _opt("84", "84-cell", "84 عين", 3),
        ],
        "sort_order": 4,
        "show_when": _gate("planting_material", _TOMATO_TRANSPLANTED),
        "is_reportable": False,
    },
    {
        "code": "rootstock_cultivar",
        "name_en": "Rootstock cultivar",
        "name_ar": "صنف الأصل",
        "value_type": "text",
        "text_max_length": 60,
        "sort_order": 5,
        "show_when": _gate("planting_material", ["grafted_seedling"]),
        "required_when": _gate("planting_material", ["grafted_seedling"]),
    },
    {
        "code": "nursery_name",
        "name_en": "Nursery",
        "name_ar": "المشتل",
        "value_type": "text",
        "text_max_length": 120,
        "sort_order": 6,
        "show_when": _gate("planting_material", _TOMATO_TRANSPLANTED),
        "is_reportable": False,
    },
]


# path → (group, definitions). Paths with 2 / 3 segments attach at the
# variety / strain level and override the inherited definition by code.
_SEED: list[tuple[str, tuple[str, str, str], list[dict[str, Any]]]] = [
    ("mango", _ESTABLISHMENT, _MANGO_CROP),
    ("citrus_orange", _ESTABLISHMENT, _CITRUS_CROP),
    ("citrus_mandarin", _ESTABLISHMENT, _CITRUS_CROP),
    ("date_palm", _PLANTING_MATERIAL, _DATE_PALM_CROP),
    ("potato", _PLANTING_MATERIAL, _POTATO_CROP),
    ("tomato", _NURSERY, _TOMATO_CROP),
    # Variety-level narrowing.
    ("mango.sukkary", _ESTABLISHMENT, [_local_rootstock("sukkary_seedling", "Sukkary", "سكري")]),
    ("mango.zebda", _ESTABLISHMENT, [_local_rootstock("zebda_seedling", "Zebda", "زبدية")]),
    # Strain-level narrowing: short-strain nursery trees arrive under 2.5 m.
    (
        "mango.alphonso.short",
        _ESTABLISHMENT,
        [
            {
                "code": "transplant_height_cm",
                "name_en": "Height at transplant",
                "name_ar": "ارتفاع الشجرة عند الشتل",
                "description_en": (
                    "Short-strain nursery trees are supplied under 2.5 m — "
                    "range narrowed from the crop-level 0–2000."
                ),
                "description_ar": (
                    "أشجار السلالة القصيرة تُورَّد بارتفاع أقل من 2.5 م — " "النطاق مختصر من 0–2000."
                ),
                "value_type": "decimal",
                "unit_en": "cm",
                "unit_ar": "سم",
                "value_min": 0,
                "value_max": 250,
                "decimal_places": 1,
                "sort_order": 4,
                "show_when": _gate("establishment_method", _MANGO_TRANSPLANTED),
            }
        ],
    ),
]


_COLUMNS = (
    "crop_id, crop_variety_id, crop_variety_strain_id, path, code, name_en, name_ar,"
    " description_en, description_ar, value_type, unit_en, unit_ar, value_min,"
    " value_max, decimal_places, text_max_length, options, is_required,"
    " required_when, show_when, group_code, group_name_en, group_name_ar,"
    " sort_order, is_reportable"
)
_VALUES = (
    ":path, :code, :name_en, :name_ar, :description_en, :description_ar,"
    " :value_type, :unit_en, :unit_ar, :value_min, :value_max, :decimal_places,"
    " :text_max_length, CAST(:options AS jsonb), :is_required,"
    " CAST(:required_when AS jsonb), CAST(:show_when AS jsonb), :group_code,"
    " :group_name_en, :group_name_ar, :sort_order, :is_reportable"
)

# One statement per attachment depth. Inner joins rather than a single
# left-joined query: a variety code that doesn't exist must insert *nothing*,
# not a row whose path claims a variety while crop_variety_id is NULL.
_INSERT_CROP = sa.text(
    f"INSERT INTO public.crop_attribute_definitions ({_COLUMNS}) "
    f"SELECT c.id, NULL, NULL, {_VALUES} "
    "FROM public.crops c WHERE c.code = :crop_code "
    "ON CONFLICT (path, code) DO NOTHING"
)
_INSERT_VARIETY = sa.text(
    f"INSERT INTO public.crop_attribute_definitions ({_COLUMNS}) "
    f"SELECT c.id, v.id, NULL, {_VALUES} "
    "FROM public.crops c "
    "JOIN public.crop_varieties v ON v.crop_id = c.id AND v.code = :variety_code "
    "WHERE c.code = :crop_code "
    "ON CONFLICT (path, code) DO NOTHING"
)
_INSERT_STRAIN = sa.text(
    f"INSERT INTO public.crop_attribute_definitions ({_COLUMNS}) "
    f"SELECT c.id, v.id, s.id, {_VALUES} "
    "FROM public.crops c "
    "JOIN public.crop_varieties v ON v.crop_id = c.id AND v.code = :variety_code "
    "JOIN public.crop_variety_strains s "
    "  ON s.crop_variety_id = v.id AND s.code = :strain_code "
    "WHERE c.code = :crop_code "
    "ON CONFLICT (path, code) DO NOTHING"
)


def _params(
    *, path: str, group: tuple[str, str, str], definition: dict[str, Any]
) -> dict[str, Any]:
    """Bind params for one definition.

    JSONB columns are bound as text and cast in SQL (``CAST(:x AS jsonb)``);
    psycopg cannot infer the type of a bare parameter inside a JSONB slot,
    which is the failure that broke #332's state-stamping SQL.
    """
    group_code, group_en, group_ar = group
    return {
        "path": path,
        "code": definition["code"],
        "name_en": definition["name_en"],
        "name_ar": definition["name_ar"],
        "description_en": definition.get("description_en"),
        "description_ar": definition.get("description_ar"),
        "value_type": definition["value_type"],
        "unit_en": definition.get("unit_en"),
        "unit_ar": definition.get("unit_ar"),
        "value_min": definition.get("value_min"),
        "value_max": definition.get("value_max"),
        "decimal_places": definition.get("decimal_places"),
        "text_max_length": definition.get("text_max_length"),
        "options": (
            json.dumps(definition["options"], ensure_ascii=False)
            if definition.get("options") is not None
            else None
        ),
        "is_required": definition.get("is_required", False),
        "required_when": (
            json.dumps(definition["required_when"], ensure_ascii=False)
            if definition.get("required_when") is not None
            else None
        ),
        "show_when": (
            json.dumps(definition["show_when"], ensure_ascii=False)
            if definition.get("show_when") is not None
            else None
        ),
        "group_code": group_code,
        "group_name_en": group_en,
        "group_name_ar": group_ar,
        "sort_order": definition["sort_order"],
        "is_reportable": definition.get("is_reportable", True),
    }


def upgrade() -> None:
    bind = op.get_bind()
    for path, group, definitions in _SEED:
        segments = path.split(".")
        if len(segments) == 1:
            stmt, extra = _INSERT_CROP, {"crop_code": segments[0]}
        elif len(segments) == 2:
            stmt = _INSERT_VARIETY
            extra = {"crop_code": segments[0], "variety_code": segments[1]}
        else:
            stmt = _INSERT_STRAIN
            extra = {
                "crop_code": segments[0],
                "variety_code": segments[1],
                "strain_code": segments[2],
            }
        for definition in definitions:
            bind.execute(stmt, {**_params(path=path, group=group, definition=definition), **extra})


def downgrade() -> None:
    """Remove exactly the seeded (path, code) pairs.

    Not a blanket delete: a platform admin may have authored attributes of
    their own on the same crops, and those are not this migration's to drop.
    """
    bind = op.get_bind()
    pairs = [(path, d["code"]) for path, _group, defs in _SEED for d in defs]
    stmt = sa.text(
        "DELETE FROM public.crop_attribute_definitions WHERE path = :path AND code = :code"
    )
    for path, code in pairs:
        bind.execute(stmt, {"path": path, "code": code})
