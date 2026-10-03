"""Medjool catalogue from the Organic Medjool Manual: calendar and attributes.

Source: *Organic Medjool Manual*, Edition 1.3, September 2026, Western Desert
of Egypt. Section numbers below refer to it.

**Calendar.** Section 12.1 maps the Medjool fruit stages (weeks after
pollination: Hababouk 1-5, Kimri 6-16, Khalal 17-20, Rutab 21-24, Tamar
25-27) onto calendar weeks from a reference pollination in week 11, and
section 12.2 assigns every week of the year to one of nine operating phases.
Week 1 starts on 1 January. Those nine phases become the nine stages here,
with the manual's own week boundaries:

====  ===============================  =======  =============
 #    phase                            weeks    dates
====  ===============================  =======  =============
 1    Winter / pre-flowering           1-5      01-01..02-04
 2    Spathe emergence & pollination   6-10     02-05..03-11
 3    Late pollination / Hababouk      11-15    03-12..04-15
 4    Kimri                            16-26    04-16..07-01
 5    Khalal                           27-30    07-02..07-29
 6    Rutab                            31-34    07-30..08-26
 7    Tamar                            35-36    08-27..09-09
 8    Harvest                          37-41    09-10..10-14
 9    Post-harvest & autumn planting   42-52    10-15..12-31
====  ===============================  =======  =============

The manual calls this mapping "an arithmetic step made by the compiler" and
asks growers to record each bunch's pollination date. Stages here follow the
calendar for the whole block; per-bunch timing is not modelled.

**No Kc.** The manual gives no crop coefficient, so no stage carries ``kc``
and the irrigation engine uses its default for these codes.

**Attributes** at ``date_palm.medjool``, only where the manual describes a
fact about the palm: palm phase (8.7, 8.8), pinnate leaves at transplant
(8.2), nursery rooting months (7.1), young-palm protection (8.4), organic
certification and certifying body (5.1). The six crop-level date palm
attributes from 0051 (propagation source, offshoot age and weight, mother
palm, tissue-culture lab and batch) already match sections 7.1 and 8.2 and
stay as they are.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0097"
down_revision: str | Sequence[str] | None = "0096"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PATH = "date_palm.medjool"


def _stage(code: str, en: str, ar: str, order: int, start: str, end: str) -> dict[str, Any]:
    return {
        "code": code,
        "name_en": en,
        "name_ar": ar,
        "order": order,
        "advance": {"mode": "calendar_doy", "start_doy": start, "end_doy": end},
    }


MEDJOOL_STAGES: dict[str, Any] = {
    "stages": [
        _stage(
            "dormancy",
            "Winter / pre-flowering",
            "الشتاء / ما قبل التزهير",
            1,
            "01-01",
            "02-04",
        ),
        _stage(
            "pollination",
            "Spathe emergence & pollination",
            "خروج الطلع والتلقيح",
            2,
            "02-05",
            "03-11",
        ),
        _stage(
            "fruit_set",
            "Late pollination / Hababouk",
            "نهاية التلقيح / الحبابوك",
            3,
            "03-12",
            "04-15",
        ),
        _stage("kimri", "Kimri (fruit growth)", "الكمري (نمو الثمار)", 4, "04-16", "07-01"),
        _stage(
            "khalal",
            "Khalal (colour change)",
            "الخلال (تغيّر اللون)",
            5,
            "07-02",
            "07-29",
        ),
        _stage("rutab", "Rutab (ripening)", "الرطب (النضج)", 6, "07-30", "08-26"),
        _stage(
            "tamar",
            "Tamar (full ripeness)",
            "التمر (اكتمال النضج)",
            7,
            "08-27",
            "09-09",
        ),
        _stage("harvest", "Harvest", "الحصاد", 8, "09-10", "10-14"),
        _stage(
            "post_harvest",
            "Post-harvest & autumn planting",
            "ما بعد الحصاد والزراعة الخريفية",
            9,
            "10-15",
            "12-31",
        ),
    ]
}


def _opt(code: str, en: str, ar: str, order: int) -> dict[str, Any]:
    return {"code": code, "name_en": en, "name_ar": ar, "sort_order": order}


_ESTABLISHMENT = ("medjool_establishment", "Establishment", "التأسيس")
_ORGANIC = ("organic", "Organic certification", "الشهادة العضوية")

_DEFINITIONS: list[tuple[tuple[str, str, str], dict[str, Any]]] = [
    (
        _ESTABLISHMENT,
        {
            "code": "palm_phase",
            "name_en": "Palm phase",
            "name_ar": "مرحلة النخلة",
            "description_en": (
                "Manual 8.7-8.8: a young palm follows the new-planting plan until it "
                "flowers, then the bearing-palm plan."
            ),
            "description_ar": (
                "الدليل 8.7-8.8: تتبع النخلة الصغيرة خطة الزراعة الجديدة حتى تُزهر، "
                "ثم خطة النخيل المثمر."
            ),
            "value_type": "single_select",
            "options": [
                _opt(
                    "new_planting",
                    "New planting (first year)",
                    "زراعة جديدة (السنة الأولى)",
                    1,
                ),
                _opt("juvenile", "Juvenile (years 2-3)", "نخلة فتية (السنة 2-3)", 2),
                _opt(
                    "onset_of_fruiting",
                    "Onset of fruiting (years 3-5)",
                    "بداية الإثمار (السنة 3-5)",
                    3,
                ),
                _opt("bearing", "Bearing palm", "نخلة مثمرة", 4),
            ],
            "is_required": True,
            "sort_order": 1,
        },
    ),
    (
        _ESTABLISHMENT,
        {
            "code": "tc_pinnate_leaves_at_planting",
            "name_en": "Pinnate leaves at transplant",
            "name_ar": "عدد الأوراق الريشية عند الشتل",
            "description_en": (
                "Manual 8.2: tissue-culture plants survived best when transplanted "
                "with 4 or more pinnate leaves."
            ),
            "description_ar": (
                "الدليل 8.2: أفضل نجاح لنباتات زراعة الأنسجة عند شتلها بأربع أوراق ريشية أو أكثر."
            ),
            "value_type": "integer",
            "unit_en": "leaves",
            "unit_ar": "ورقة",
            "value_min": 0,
            "value_max": 30,
            "sort_order": 2,
        },
    ),
    (
        _ESTABLISHMENT,
        {
            "code": "nursery_rooting_months",
            "name_en": "Nursery rooting period",
            "name_ar": "مدة التجذير في المشتل",
            "description_en": (
                "Manual 7.1: an offshoot is rooted in a nursery for 1-2 years before "
                "field planting."
            ),
            "description_ar": "الدليل 7.1: تُجذَّر الفسيلة في المشتل سنة إلى سنتين قبل الزراعة في الحقل.",
            "value_type": "integer",
            "unit_en": "months",
            "unit_ar": "شهر",
            "value_min": 0,
            "value_max": 48,
            "sort_order": 3,
        },
    ),
    (
        _ESTABLISHMENT,
        {
            "code": "young_palm_protection",
            "name_en": "Young palm protection",
            "name_ar": "حماية النخلة الصغيرة",
            "description_en": (
                "Manual 8.4: protect from sun and wind in the first summer and from "
                "cold the following winter."
            ),
            "description_ar": (
                "الدليل 8.4: الحماية من الشمس والرياح في الصيف الأول ومن البرد في الشتاء التالي."
            ),
            "value_type": "single_select",
            "options": [
                _opt("hessian", "Hessian wrapping", "لف بالخيش", 1),
                _opt("shade_net", "Shade net", "شبكة تظليل", 2),
                _opt("date_leaf_tent", "Tent of date leaves", "خيمة من سعف النخيل", 3),
                _opt("none", "None", "بدون", 4),
            ],
            "sort_order": 4,
        },
    ),
    (
        _ORGANIC,
        {
            "code": "organic_certified",
            "name_en": "Certified organic",
            "name_ar": "معتمد عضويًا",
            "description_en": (
                "Manual 5.1: organic farming in Egypt is governed by Law No. 12 of 2020."
            ),
            "description_ar": "الدليل 5.1: تخضع الزراعة العضوية في مصر للقانون رقم 12 لسنة 2020.",
            "value_type": "boolean",
            "sort_order": 1,
        },
    ),
    (
        _ORGANIC,
        {
            "code": "certifying_body",
            "name_en": "Certifying body",
            "name_ar": "جهة الاعتماد",
            "description_en": (
                "Manual 5.1: check every input against this body's list of permitted inputs."
            ),
            "description_ar": "الدليل 5.1: راجع كل مُدخل مقابل قائمة المدخلات المسموح بها لدى هذه الجهة.",
            "value_type": "text",
            "text_max_length": 200,
            "sort_order": 2,
        },
    ),
]

_COLUMNS = (
    "crop_id, crop_variety_id, crop_variety_strain_id, path, code, name_en, name_ar,"
    " description_en, description_ar, value_type, unit_en, unit_ar, value_min,"
    " value_max, decimal_places, text_max_length, options, is_required,"
    " required_when, show_when, group_code, group_name_en, group_name_ar,"
    " sort_order, is_reportable"
)
_INSERT_VARIETY = sa.text(
    f"INSERT INTO public.crop_attribute_definitions ({_COLUMNS}) "  # noqa: S608 - constant columns
    "SELECT c.id, v.id, NULL, :path, :code, :name_en, :name_ar, :description_en,"
    " :description_ar, :value_type, :unit_en, :unit_ar, :value_min, :value_max,"
    " NULL, :text_max_length, CAST(:options AS jsonb), :is_required,"
    " NULL, NULL, :group_code, :group_name_en, :group_name_ar, :sort_order, TRUE "
    "FROM public.crops c "
    "JOIN public.crop_varieties v ON v.crop_id = c.id AND v.code = 'medjool' "
    "WHERE c.code = 'date_palm' "
    "ON CONFLICT (path, code) DO NOTHING"
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE public.crop_varieties SET phenology_stages_override = CAST(:stages AS jsonb) "
            "WHERE path = :path"
        ),
        {"stages": json.dumps(MEDJOOL_STAGES, ensure_ascii=False), "path": _PATH},
    )
    for (group_code, group_en, group_ar), d in _DEFINITIONS:
        conn.execute(
            _INSERT_VARIETY,
            {
                "path": _PATH,
                "code": d["code"],
                "name_en": d["name_en"],
                "name_ar": d["name_ar"],
                "description_en": d.get("description_en"),
                "description_ar": d.get("description_ar"),
                "value_type": d["value_type"],
                "unit_en": d.get("unit_en"),
                "unit_ar": d.get("unit_ar"),
                "value_min": d.get("value_min"),
                "value_max": d.get("value_max"),
                "text_max_length": d.get("text_max_length"),
                "options": (
                    json.dumps(d["options"], ensure_ascii=False) if d.get("options") else None
                ),
                "is_required": d.get("is_required", False),
                "group_code": group_code,
                "group_name_en": group_en,
                "group_name_ar": group_ar,
                "sort_order": d["sort_order"],
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM public.crop_attribute_definitions "
            "WHERE path = :path AND code = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))),
        {"path": _PATH, "codes": [d["code"] for _, d in _DEFINITIONS]},
    )
    conn.execute(
        sa.text(
            "UPDATE public.crop_varieties SET phenology_stages_override = NULL WHERE path = :path"
        ),
        {"path": _PATH},
    )
