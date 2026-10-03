"""Use the Arabic edition of the Organic Medjool Manual for the Medjool seed.

0097-0099 carried Arabic written before the manual's Arabic edition was
available. This replaces it with the manual's own terms (Edition 1.3,
September 2026, Arabic view): the nine phase names from section 12.2, and
the wording of sections 5, 7-12 for attributes, signals and templates.

The English stage names move to the section 12.2 phase labels at the same
time, so both languages name a stage the way the manual does.

Notable term changes: black nose is «الذنب الأسود», bunch bending is
«تدلية العذوق», Deglet Noor is «دجلة نور», harvest passes are «دفعات الجني».
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0100"
down_revision: str | Sequence[str] | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PATH = "date_palm.medjool"


def _json(value: object) -> object:
    """A JSONB value as Python, whichever form the driver returns it in."""
    return json.loads(value) if isinstance(value, str) else value


# code -> (name_en, name_ar), section 12.2 phase labels.
STAGE_NAMES: dict[str, tuple[str, str]] = {
    "dormancy": ("Winter / pre-flowering", "الشتاء / ما قبل التزهير"),
    "pollination": ("Spathe emergence & pollination", "ظهور الطلع والتلقيح"),
    "fruit_set": ("Late pollination / Hababouk", "آخر التلقيح / الحبابوك"),
    "kimri": ("Kimri", "الكمري"),
    "khalal": ("Khalal", "الخلال"),
    "rutab": ("Rutab", "الرطب"),
    "tamar": ("Tamar", "التمر"),
    "harvest": ("Harvest", "الحصاد"),
    "post_harvest": (
        "Post-harvest & autumn planting",
        "ما بعد الحصاد والزراعة الخريفية",
    ),
}

# code -> (name_ar, description_ar, unit_ar, {option_code: name_ar}, group_name_ar)
ATTRIBUTES: dict[str, tuple[str, str, str | None, dict[str, str], str]] = {
    "palm_phase": (
        "طور النخلة",
        "الدليل 8.7-8.8: تتبع النخلة الصغيرة الخطة الزمنية من الزراعة حتى بداية الإثمار، "
        "ثم الخطة الأسبوعية للنخيل المثمر عند دخولها الطور الثمري.",
        None,
        {
            "new_planting": "السنة الأولى بعد الزراعة",
            "juvenile": "النمو الخضري (الطور اليافع)",
            "onset_of_fruiting": "بداية الإثمار",
            "bearing": "نخلة مثمرة",
        },
        "التأسيس",
    ),
    "tc_pinnate_leaves_at_planting": (
        "عدد الأوراق الريشية عند النقل إلى الحقل",
        "الدليل 8.2: تحققت أفضل نسبة بقاء في الحقل عند نقل نباتات زراعة الأنسجة في طور "
        "أربع أوراق ريشية أو أكثر.",
        "ورقة",
        {},
        "التأسيس",
    ),
    "nursery_rooting_months": (
        "فترة التجذير في المشتل",
        "الدليل 7.1: لا ينبغي زراعة الفسيلة في الحقل مباشرةً بعد فصلها؛ ويُنصح بفترة تجذير "
        "في المشتل مدتها سنة إلى سنتين.",
        "شهر",
        {},
        "التأسيس",
    ),
    "young_palm_protection": (
        "حماية النخلة الصغيرة",
        "الدليل 8.4: الحماية من الشمس والرياح في الصيف الأول ومن البرد في الشتاء التالي ومن "
        "الحيوانات كالأرانب.",
        None,
        {
            "hessian": "لف الخيش",
            "shade_net": "غطاء من شبك التظليل",
            "date_leaf_tent": "خيمة من سعف النخيل",
            "none": "بدون",
        },
        "التأسيس",
    ),
    "organic_certified": (
        "معتمد عضويًا",
        "الدليل 5.1: تخضع الزراعة العضوية في مصر للقانون رقم 12 لسنة 2020.",
        None,
        {},
        "الاعتماد العضوي",
    ),
    "certifying_body": (
        "جهة الاعتماد",
        "الدليل 5.1: ينبغي التحقق من كل مدخل مقابل قائمة المدخلات المسموح بها لدى جهة "
        "الاعتماد قبل الاستخدام.",
        None,
        {},
        "الاعتماد العضوي",
    ),
}

# code -> (name_ar, description_ar, unit_ar, categorical_values_ar)
SIGNALS: dict[str, tuple[str, str, str | None, list[str] | None]] = {
    "date_rpw_trap_catch": (
        "أعداد سوسة النخيل الحمراء في المصيدة",
        "الدليل 10.1: تُخدم المصائد الفرمونية (تغيير الطعم الغذائي والماء) كل 7-14 يومًا مع "
        "تسجيل أعداد الحشرات الملتقطة. القيمة التي تقرؤها الشجرة هي عدد سجلات المصائد خلال 14 يومًا.",
        "حشرة لكل مصيدة",
        None,
    ),
    "date_rpw_infested_palm": (
        "وجود نخلة مصابة بسوسة النخيل الحمراء",
        "الدليل 10.1: المعاينة البصرية للنخيل ومعرفة أطوار الإصابة وأعراضها. سجّل «لا» بعد "
        "إزالة النخلة المصابة.",
        None,
        None,
    ),
    "date_rpw_palm_removed": (
        "إزالة نخلة شديدة الإصابة والتخلص منها",
        "الدليل 10.1: إزالة النخيل شديد الإصابة والتخلص منه.",
        None,
        None,
    ),
    "date_bunches_pollinated": (
        "عدد العذوق الملقّحة",
        "الدليل 9.1 و12.1: سجّل تاريخ تلقيح كل عذق واحسب منه مواعيد الخفّ والتكييس. تاريخ "
        "الملاحظة هو تاريخ التلقيح.",
        "عذق",
        None,
    ),
    "date_strands_per_bunch": (
        "عدد الشماريخ في العذق بعد الخفّ",
        "الدليل 9.2: نحو 30 شمراخًا للعذق (إسرائيل) أو نحو 35 شمراخًا (أريزونا).",
        "شمراخ",
        None,
    ),
    "date_fruits_per_strand": (
        "عدد الثمار في الشمراخ بعد الخفّ",
        "الدليل 9.2: 10 ثمار لكل شمراخ (إسرائيل) أو 15-20 ثمرة (أريزونا).",
        "ثمرة",
        None,
    ),
    "date_bunches_per_palm": (
        "عدد العذوق في النخلة",
        "الدليل 9.2: لا يُترك عادةً أكثر من 15 عذقًا (مرجع دجلة نور).",
        "عذق",
        None,
    ),
    "date_leaves_per_palm": (
        "عدد الأوراق الخضراء في النخلة",
        "الدليل 9.2: نسبة 8-9 أوراق لكل عذق (مرجع دجلة نور).",
        "ورقة",
        None,
    ),
    "date_dust_mite_found": (
        "وجود حلم الغبار على العذوق",
        "الدليل 10.3: فحص العذوق بحثًا عن حلم الغبار (Oligonychus afrasiaticus).",
        None,
        None,
    ),
    "date_ripening_stage": (
        "طور النضج داخل الأكياس",
        "الدليل 12.2 الأسابيع 29-36: متابعة تقدم النضج داخل الأكياس.",
        None,
        ["الخلال", "الرطب", "التمر"],
    ),
    "date_fruit_cracking_seen": (
        "ظهور تشقق الثمار",
        "الدليل 9.6: التغيرات المفاجئة في رطوبة التربة وامتلاء الثمار من الأسباب الرئيسية "
        "لتشقق الثمار.",
        None,
        None,
    ),
    "date_black_nose_seen": (
        "ظهور الذنب الأسود",
        "الدليل 9.4: انكماش طرف الثمرة وتلوّنه بالداكن، وينتج أساسًا عن الطقس الرطب في طور الخلال.",
        None,
        None,
    ),
    "date_harvest_pass": (
        "رقم دفعة الجني",
        "الدليل 11.1: يُجرى الجني على دفعتين وأحيانًا ثلاث، تفصل بينها عادةً أسبوع إلى أسبوعين.",
        None,
        None,
    ),
    "date_new_growth_seen": (
        "ظهور نمو جديد على النخلة المزروعة حديثًا",
        "الدليل 8.8 الأسبوع 6: تسجيل النباتات التي ظهر عليها نمو جديد.",
        None,
        None,
    ),
    "date_soil_pulled_away": (
        "جفاف التربة السطحية وانكماشها بعيدًا عن النبات",
        "الدليل 8.5: خلال الأسابيع الستة الأولى تُفحص النباتات للتأكد من أن التربة السطحية لا "
        "تجف ولا تنكمش بعيدًا عن النبات.",
        None,
        None,
    ),
}

SIGNAL_TEMPLATES: dict[str, str] = {
    "medjool_bearing": "نخيل المجدول المثمر",
    "medjool_new_planting": "الزراعات الجديدة للمجدول",
}

# code -> (name_ar, description_ar)
PLAN_TEMPLATES: dict[str, tuple[str, str]] = {
    "medjool-organic-bearing-eg": (
        "المجدول العضوي — النخيل المثمر (الصحراء الغربية بمصر)",
        "خطة العمل الزراعية الأسبوعية (52 أسبوعًا) من دليل المجدول العضوي، الإصدار 1.3، "
        "القسم 12. تتبع الأنشطة مراحل المجدول التسع.",
    ),
    "medjool-organic-new-planting-eg": (
        "المجدول العضوي — من الزراعة حتى بداية الإثمار (الصحراء الغربية بمصر)",
        "الخطة الزمنية من الزراعة حتى بداية الإثمار، من 8 أسابيع قبل الزراعة حتى السنة "
        "الخامسة، من دليل المجدول العضوي، القسم 8.8. اجعل تاريخ بدء الخطة أسبوع الزراعة في الحقل.",
    ),
}


def upgrade() -> None:
    conn = op.get_bind()

    override = _json(
        conn.execute(
            sa.text(
                "SELECT phenology_stages_override FROM public.crop_varieties WHERE path = :p"
            ),
            {"p": _PATH},
        ).scalar()
    )
    if override:
        for stage in override["stages"]:
            if stage["code"] in STAGE_NAMES:
                stage["name_en"], stage["name_ar"] = STAGE_NAMES[stage["code"]]
        conn.execute(
            sa.text(
                "UPDATE public.crop_varieties SET phenology_stages_override = CAST(:o AS jsonb) "
                "WHERE path = :p"
            ),
            {"o": json.dumps(override, ensure_ascii=False), "p": _PATH},
        )

    for code, (
        name_ar,
        description_ar,
        unit_ar,
        options_ar,
        group_ar,
    ) in ATTRIBUTES.items():
        options = _json(
            conn.execute(
                sa.text(
                    "SELECT options FROM public.crop_attribute_definitions "
                    "WHERE path = :p AND code = :c"
                ),
                {"p": _PATH, "c": code},
            ).scalar()
        )
        if options:
            for option in options:
                option["name_ar"] = options_ar.get(option["code"], option["name_ar"])
        conn.execute(
            sa.text(
                "UPDATE public.crop_attribute_definitions SET name_ar = :name_ar, "
                " description_ar = :description_ar, unit_ar = COALESCE(:unit_ar, unit_ar), "
                " options = CAST(:options AS jsonb), group_name_ar = :group_ar "
                "WHERE path = :p AND code = :c"
            ),
            {
                "name_ar": name_ar,
                "description_ar": description_ar,
                "unit_ar": unit_ar,
                "options": json.dumps(options, ensure_ascii=False) if options else None,
                "group_ar": group_ar,
                "p": _PATH,
                "c": code,
            },
        )

    for code, (name_ar, description_ar, unit_ar, values_ar) in SIGNALS.items():
        conn.execute(
            sa.text(
                "UPDATE public.signal_definitions SET name_ar = :name_ar, "
                " description_ar = :description_ar, unit_ar = :unit_ar, "
                " categorical_values_ar = COALESCE(CAST(:values_ar AS text[]), categorical_values_ar) "
                "WHERE code = :c AND tenant_id IS NULL"
            ),
            {
                "name_ar": name_ar,
                "description_ar": description_ar,
                "unit_ar": unit_ar,
                "values_ar": values_ar,
                "c": code,
            },
        )

    for code, name_ar in SIGNAL_TEMPLATES.items():
        conn.execute(
            sa.text(
                "UPDATE public.signal_templates SET name_ar = :n "
                "WHERE code = :c AND tenant_id IS NULL"
            ),
            {"n": name_ar, "c": code},
        )

    for code, (name_ar, description_ar) in PLAN_TEMPLATES.items():
        conn.execute(
            sa.text(
                "UPDATE public.plan_templates SET name_ar = :n, description_ar = :d "
                "WHERE code = :c AND deleted_at IS NULL"
            ),
            {"n": name_ar, "d": description_ar, "c": code},
        )


def downgrade() -> None:
    # Text-only revision. The 0097-0099 Arabic it replaced was a translation
    # made before the manual's Arabic edition existed; it is not restored.
    pass
