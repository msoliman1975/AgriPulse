"""Medjool scouting signals and two forms, from the Organic Medjool Manual.

Each signal is something the manual asks the grower to record or inspect.
Section numbers refer to the manual (Edition 1.3, September 2026).

Signals are platform definitions with ``date_`` codes. A platform signal
cannot be limited to one crop, so the prefix is what keeps them apart from
the general scouting set in 0053. A tenant sees them only after assigning
them to a farm or block; the decision trees read them through that
assignment.

Observations stop at block level. The manual's per-bunch records (pollination
date, strands per bunch) become block-level values here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0098"
down_revision: str | Sequence[str] | None = "0097"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, name_en, name_ar, value_kind, categorical_values, categorical_values_ar,
#  unit_en, unit_ar, value_min, value_max, aggregation, window_days,
#  description_en, description_ar)
DEFINITIONS: tuple[tuple, ...] = (
    (
        "date_rpw_trap_catch",
        "Red palm weevil trap catch",
        "حصيلة مصيدة سوسة النخيل الحمراء",
        "numeric",
        None,
        None,
        "weevils per trap",
        "سوسة لكل مصيدة",
        0,
        10000,
        "count",
        14,
        "Manual 10.1: service each pheromone trap every 7-14 days and record its "
        "catch. The value a tree reads is the number of trap records in 14 days.",
        "الدليل 10.1: تُخدم كل مصيدة فرمونية كل 7-14 يومًا وتُسجَّل حصيلتها. "
        "القيمة التي تقرؤها الشجرة هي عدد سجلات المصائد خلال 14 يومًا.",
    ),
    (
        "date_rpw_infested_palm",
        "Red palm weevil infested palm found",
        "وجود نخلة مصابة بسوسة النخيل الحمراء",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 10.1: visual inspection for weevil symptoms. Record No once the "
        "infested palm is removed.",
        "الدليل 10.1: فحص بصري لأعراض السوسة. سجّل لا بعد إزالة النخلة المصابة.",
    ),
    (
        "date_rpw_palm_removed",
        "Heavily infested palm removed",
        "إزالة نخلة شديدة الإصابة",
        "event",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 10.1: heavily infested palms are removed and disposed of.",
        "الدليل 10.1: تُزال النخيل شديدة الإصابة ويُتخلَّص منها.",
    ),
    (
        "date_bunches_pollinated",
        "Bunches pollinated",
        "عدد العذوق الملقحة",
        "numeric",
        None,
        None,
        "bunches",
        "عذق",
        0,
        100000,
        "sum",
        60,
        "Manual 9.1 and 12.1: record the pollination date of each bunch. The "
        "observation date is the pollination date.",
        "الدليل 9.1 و12.1: سجّل تاريخ تلقيح كل عذق. تاريخ الملاحظة هو تاريخ التلقيح.",
    ),
    (
        "date_strands_per_bunch",
        "Strands per bunch after thinning",
        "عدد الشماريخ في العذق بعد الخف",
        "numeric",
        None,
        None,
        "strands",
        "شمراخ",
        0,
        200,
        "mean",
        30,
        "Manual 9.2: about 30 strands per bunch (Israel) or about 35 (Arizona).",
        "الدليل 9.2: نحو 30 شمراخًا في العذق (إسرائيل) أو نحو 35 (أريزونا).",
    ),
    (
        "date_fruits_per_strand",
        "Fruits per strand after thinning",
        "عدد الثمار في الشمراخ بعد الخف",
        "numeric",
        None,
        None,
        "fruits",
        "ثمرة",
        0,
        100,
        "mean",
        30,
        "Manual 9.2: about 10 fruits per strand (Israel) or 15-20 (Arizona).",
        "الدليل 9.2: نحو 10 ثمار في الشمراخ (إسرائيل) أو 15-20 (أريزونا).",
    ),
    (
        "date_bunches_per_palm",
        "Bunches per palm",
        "عدد العذوق في النخلة",
        "numeric",
        None,
        None,
        "bunches",
        "عذق",
        0,
        60,
        "mean",
        60,
        "Manual 9.2: usually no more than 15 bunches (a Deglet Noor reference).",
        "الدليل 9.2: عادة لا يزيد عن 15 عذقًا (مرجع دقلة نور).",
    ),
    (
        "date_leaves_per_palm",
        "Green leaves per palm",
        "عدد الأوراق الخضراء في النخلة",
        "numeric",
        None,
        None,
        "leaves",
        "ورقة",
        0,
        300,
        "mean",
        60,
        "Manual 9.2: 8-9 leaves per bunch (a Deglet Noor reference).",
        "الدليل 9.2: 8-9 أوراق لكل عذق (مرجع دقلة نور).",
    ),
    (
        "date_dust_mite_found",
        "Dust mite found on bunches",
        "وجود حلم الغبار على العذوق",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 10.3: scout bunches for the date palm dust mite (Oligonychus " "afrasiaticus).",
        "الدليل 10.3: افحص العذوق بحثًا عن حلم غبار النخيل.",
    ),
    (
        "date_ripening_stage",
        "Ripening stage seen in the bags",
        "مرحلة النضج داخل الأكياس",
        "categorical",
        ["khalal", "rutab", "tamar"],
        ["خلال", "رطب", "تمر"],
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 12.2 weeks 29-36: monitor ripening inside the bags.",
        "الدليل 12.2 الأسابيع 29-36: تابع النضج داخل الأكياس.",
    ),
    (
        "date_fruit_cracking_seen",
        "Fruit cracking seen",
        "ظهور تشقق الثمار",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 9.6: abrupt changes in soil moisture are a main cause of cracking.",
        "الدليل 9.6: التغير المفاجئ في رطوبة التربة سبب رئيسي للتشقق.",
    ),
    (
        "date_black_nose_seen",
        "Black nose seen",
        "ظهور اسوداد طرف الثمرة",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 9.4: shrivelling and darkening of the fruit tip, mainly from humid "
        "weather at Khalal.",
        "الدليل 9.4: ذبول طرف الثمرة واسوداده وسببه الرئيسي الطقس الرطب في مرحلة الخلال.",
    ),
    (
        "date_harvest_pass",
        "Harvest pass number",
        "رقم جولة الحصاد",
        "numeric",
        None,
        None,
        None,
        None,
        1,
        3,
        "latest",
        None,
        "Manual 11.1: Medjool is picked in 2, sometimes 3, passes 1-2 weeks apart.",
        "الدليل 11.1: يُجنى المجدول على جولتين وأحيانًا ثلاث بفاصل أسبوع إلى أسبوعين.",
    ),
    (
        "date_new_growth_seen",
        "New growth on a new planting",
        "ظهور نمو جديد على النخلة المزروعة حديثًا",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 8.4 and 8.8 week 6: record plants showing new growth.",
        "الدليل 8.4 و8.8 الأسبوع 6: سجّل النباتات التي ظهر عليها نمو جديد.",
    ),
    (
        "date_soil_pulled_away",
        "Soil dried and pulled away from the plant",
        "جفاف التربة وانفصالها عن النبات",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        "latest",
        None,
        "Manual 8.5: in the first 6 weeks the surface soil must not dry and shrink "
        "away from the plant.",
        "الدليل 8.5: في الأسابيع الستة الأولى يجب ألا تجف التربة السطحية وتنفصل عن النبات.",
    ),
)

# (code, name_en, name_ar, description_en, description_ar, members[(code, required)])
TEMPLATES: tuple[tuple, ...] = (
    (
        "medjool_bearing",
        "Medjool bearing palms",
        "نخيل المجدول المثمر",
        "Organic Medjool Manual sections 9-11: weevil, pollination, thinning, "
        "bunch health and harvest.",
        "دليل المجدول العضوي الأقسام 9-11: السوسة والتلقيح والخف وصحة العذوق والحصاد.",
        [
            ("date_rpw_trap_catch", False),
            ("date_rpw_infested_palm", False),
            ("date_rpw_palm_removed", False),
            ("date_bunches_pollinated", False),
            ("date_strands_per_bunch", False),
            ("date_fruits_per_strand", False),
            ("date_bunches_per_palm", False),
            ("date_leaves_per_palm", False),
            ("date_dust_mite_found", False),
            ("date_ripening_stage", False),
            ("date_fruit_cracking_seen", False),
            ("date_black_nose_seen", False),
            ("date_harvest_pass", False),
        ],
    ),
    (
        "medjool_new_planting",
        "Medjool new plantings",
        "زراعات المجدول الجديدة",
        "Organic Medjool Manual section 8: establishment checks for young palms.",
        "دليل المجدول العضوي القسم 8: فحوص التأسيس للنخيل الصغير.",
        [
            ("date_soil_pulled_away", False),
            ("date_new_growth_seen", False),
            ("date_rpw_trap_catch", False),
            ("date_rpw_infested_palm", False),
        ],
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    for (
        code,
        name_en,
        name_ar,
        value_kind,
        values,
        values_ar,
        unit_en,
        unit_ar,
        value_min,
        value_max,
        aggregation,
        window_days,
        description_en,
        description_ar,
    ) in DEFINITIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO public.signal_definitions (
                    tenant_id, code, name, name_ar, description, description_ar,
                    value_kind, unit, unit_ar, categorical_values,
                    categorical_values_ar, value_min, value_max,
                    attachment_allowed, is_active, aggregation,
                    aggregation_window_days
                )
                SELECT NULL, :code, :name, :name_ar, :description, :description_ar,
                       :value_kind, :unit, :unit_ar,
                       CAST(:categorical_values AS text[]),
                       CAST(:categorical_values_ar AS text[]),
                       :value_min, :value_max, TRUE, TRUE, :aggregation, :window_days
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.signal_definitions
                     WHERE code = :code AND tenant_id IS NULL
                 )
                """
            ),
            {
                "code": code,
                "name": name_en,
                "name_ar": name_ar,
                "description": description_en,
                "description_ar": description_ar,
                "value_kind": value_kind,
                "unit": unit_en,
                "unit_ar": unit_ar,
                "categorical_values": values,
                "categorical_values_ar": values_ar,
                "value_min": value_min,
                "value_max": value_max,
                "aggregation": aggregation,
                "window_days": window_days,
            },
        )

    for (
        template_code,
        name_en,
        name_ar,
        description_en,
        _description_ar,
        members,
    ) in TEMPLATES:
        conn.execute(
            sa.text(
                """
                INSERT INTO public.signal_templates
                       (tenant_id, code, name, name_ar, description, is_active)
                SELECT NULL, :code, :name, :name_ar, :description, TRUE
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.signal_templates
                     WHERE code = :code AND tenant_id IS NULL
                 )
                """
            ),
            {
                "code": template_code,
                "name": name_en,
                "name_ar": name_ar,
                "description": description_en,
            },
        )
        for position, (definition_code, is_required) in enumerate(members):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO public.signal_template_definitions
                           (template_id, signal_definition_id, position, is_required)
                    SELECT t.id, d.id, :position, :is_required
                      FROM public.signal_templates t
                      JOIN public.signal_definitions d
                        ON d.code = :definition_code AND d.tenant_id IS NULL
                     WHERE t.code = :template_code AND t.tenant_id IS NULL
                       AND NOT EXISTS (
                          SELECT 1 FROM public.signal_template_definitions x
                           WHERE x.template_id = t.id AND x.signal_definition_id = d.id
                       )
                    """
                ),
                {
                    "template_code": template_code,
                    "definition_code": definition_code,
                    "position": position,
                    "is_required": is_required,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    template_codes = [t[0] for t in TEMPLATES]
    definition_codes = [d[0] for d in DEFINITIONS]
    conn.execute(
        sa.text(
            "DELETE FROM public.signal_template_definitions WHERE template_id IN ("
            " SELECT id FROM public.signal_templates"
            " WHERE tenant_id IS NULL AND code = ANY(:codes))"
        ).bindparams(sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))),
        {"codes": template_codes},
    )
    conn.execute(
        sa.text(
            "DELETE FROM public.signal_templates WHERE tenant_id IS NULL AND code = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))),
        {"codes": template_codes},
    )
    conn.execute(
        sa.text(
            "DELETE FROM public.signal_definitions WHERE tenant_id IS NULL AND code = ANY(:codes)"
        ).bindparams(sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))),
        {"codes": definition_codes},
    )
