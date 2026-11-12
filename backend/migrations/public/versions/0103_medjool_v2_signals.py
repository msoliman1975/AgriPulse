"""Medjool v2 scouting signals and five scout forms (decisions D5-D7, D14, D21).

The 27 signals the Medjool v2 decision trees read, with the `date_` prefix
(D5). Each description is the question the tree asks, in English and in Arabic,
taken from the trees documents. Kinds and windows follow the approved draft
(D14):

* a window on a `latest` signal is how long an answer stays valid (D6); an
  older answer reads as missing;
* "done" records (`date_rpw_inspection_done`, `date_trap_serviced`,
  `date_bunches_scouted`) are events; trees read `days_since_latest`;
* `date_rpw_trap_catch_value` is the catch per trap at service (D7), next to
  the existing count-of-records signal `date_rpw_trap_catch`.

Every row here, and the 15 `date_` signals and two forms of public 0098, is
scoped to `date_palm.medjool` (D21): they switch on by themselves for Medjool
blocks and the scout app offers them only there. Short names are drafts; the
Arabic ones are listed for the Arabic reviewer (D26).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103"
down_revision: str | Sequence[str] | None = "0102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPE = ["date_palm.medjool"]

# (code, name_en, name_ar, value_kind, categorical_values, categorical_values_ar,
#  unit_en, unit_ar, value_min, value_max, window_days,
#  description_en, description_ar). Aggregation is `latest` for all.
DEFINITIONS: tuple[tuple, ...] = (
    (
        "date_rpw_symptom_seen",
        "RPW signs seen",
        "علامات سوسة النخيل الحمراء",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Has a scout reported RPW signs (egg notches, holes, oozing brown fluid, chewed fibre, cocoons, off-centre crown)?",
        "تسأل أشجار المجدول: هل أبلغ المستكشف عن علامات السوسة (ثقوب وضع البيض، ثقوب، سائل بني، ألياف ممضوغة، شرانق، قمة مائلة)؟",
    ),
    (
        "date_offshoot_or_frond_cut",
        "Offshoots removed or fronds cut",
        "فصل فسائل أو قطع سعف",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        7,
        "Medjool trees ask: Were offshoots removed or fronds cut in the last week?",
        "تسأل أشجار المجدول: هل فُصلت فسائل أو قُطع سعف خلال الأسبوع الماضي؟",
    ),
    (
        "date_wounds_treated",
        "Cuts treated",
        "معالجة الجروح",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        7,
        "Medjool trees ask: Were the cuts given a protective treatment?",
        "تسأل أشجار المجدول: هل عولجت الجروح معالجة وقائية؟",
    ),
    (
        "date_aerial_roots_exposed",
        "Aerial roots exposed",
        "جذور هوائية مكشوفة",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Are aerial roots at the palm base left uncovered?",
        "تسأل أشجار المجدول: هل الجذور الهوائية عند قاعدة النخلة مكشوفة؟",
    ),
    (
        "date_rodent_damage_seen",
        "Rodent damage at palm bases",
        "ضرر فئران عند قواعد النخيل",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Is there rat or mouse feeding damage at palm bases?",
        "تسأل أشجار المجدول: هل يوجد ضرر تغذية فئران عند قواعد النخيل؟",
    ),
    (
        "date_infested_waste_left",
        "Infested palm waste left",
        "مخلفات نخيل مصابة متروكة",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Is infested palm waste left beside paths or field edges?",
        "تسأل أشجار المجدول: هل تُركت مخلفات نخيل مصابة بجوار الممرات أو الحواف؟",
    ),
    (
        "date_rpw_trap_catch_value",
        "RPW catch per trap",
        "صيد سوسة النخيل لكل مصيدة",
        "numeric",
        None,
        None,
        "weevils per trap",
        "سوسة لكل مصيدة",
        0,
        10000,
        15,
        "Medjool trees ask: Is the trap catch per trap per fortnight at or above the action level?",
        "تسأل أشجار المجدول: هل الصيد لكل مصيدة كل أسبوعين عند حد التدخل أو أعلى؟",
    ),
    (
        "date_rpw_inspection_done",
        "RPW inspection done",
        "تم فحص سوسة النخيل",
        "event",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "Medjool trees ask: Has it been more than a month since every palm was inspected?",
        "تسأل أشجار المجدول: هل مر أكثر من شهر منذ فحص كل النخيل؟",
    ),
    (
        "date_trap_serviced",
        "Trap serviced",
        "تمت خدمة المصيدة",
        "event",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "Medjool trees ask: Have traps gone more than 15 days without new bait and water?",
        "تسأل أشجار المجدول: هل مرّ على المصائد أكثر من 15 يومًا دون تجديد الطعم والماء؟",
    ),
    (
        "date_mite_webbing_seen",
        "Dust mite webbing on bunches",
        "نسيج حلم الغبار على العذوق",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        7,
        "Medjool trees ask: Has a scout seen webbing and dust on bunches?",
        "تسأل أشجار المجدول: هل رأى المستكشف نسيجًا وغبارًا على العذوق؟",
    ),
    (
        "date_hollow_fruit_seen",
        "Dropped or hollow young fruit",
        "ثمار صغيرة متساقطة أو مجوّفة",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        7,
        "Medjool trees ask: Has a scout seen dropped or hollow young fruit?",
        "تسأل أشجار المجدول: هل رأى المستكشف ثمارًا صغيرة متساقطة أو مجوّفة؟",
    ),
    (
        "date_spathe_rot_seen",
        "Rotted spathes",
        "طلع متعفن",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        7,
        "Medjool trees ask: Has a scout seen rotted spathes?",
        "تسأل أشجار المجدول: هل رأى المستكشف طلعًا متعفنًا؟",
    ),
    (
        "date_bunches_bagged",
        "Bunches bagged",
        "العذوق مكيّسة",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "Medjool trees ask: Are the bunches bagged?",
        "تسأل أشجار المجدول: هل العذوق مكيّسة؟",
    ),
    (
        "date_bunches_scouted",
        "Bunches scouted",
        "تم فحص العذوق",
        "event",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "Medjool trees ask: Has it been more than 7 days since bunches were scouted?",
        "تسأل أشجار المجدول: هل مرّ أكثر من 7 أيام منذ فحص العذوق؟",
    ),
    (
        "date_charcoal_lesions_seen",
        "Charcoal-like lesions",
        "بقع فحمية",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Are dark, hard, charcoal-like lesions seen on fronds, spathes or the heart?",
        "تسأل أشجار المجدول: هل تُرى بقع داكنة صلبة فحمية على السعف أو الطلع أو القلب؟",
    ),
    (
        "date_rachis_one_side_whitening",
        "Rachis whitening on one side",
        "ابيضاض جهة من العرق الوسطي",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Is one side of the rachis whitening from base to tip?",
        "تسأل أشجار المجدول: هل تبيضّ جهة من العرق الوسطي من القاعدة إلى القمة؟",
    ),
    (
        "date_leaf_base_rot_seen",
        "Lower frond bases rotting",
        "تعفن قواعد السعف السفلي",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Are the bases of the lower fronds rotting?",
        "تسأل أشجار المجدول: هل تتعفن قواعد السعف السفلي؟",
    ),
    (
        "date_yellow_streaking_stunting",
        "Yellow streaking and stunting (Al-Wijam)",
        "تخطيط أصفر وتقزم (الوجام)",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Are leaves stunted with yellow streaks and fruit stalks smaller (Al-Wijam pattern)?",
        "تسأل أشجار المجدول: هل الأوراق متقزمة بتخطيط أصفر والعراجين أصغر (نمط الوجام)؟",
    ),
    (
        "date_brittle_leaflets_seen",
        "Brittle, dull olive leaflets",
        "وريقات زيتونية باهتة هشة",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Are leaflets dull olive, brittle and breaking easily?",
        "تسأل أشجار المجدول: هل الوريقات زيتونية باهتة هشة سهلة الكسر؟",
    ),
    (
        "date_graphiola_spots_seen",
        "Graphiola sori on the oldest fronds",
        "بثرات الجرافيولا على أقدم السعف",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Are black Graphiola sori seen on the oldest fronds?",
        "تسأل أشجار المجدول: هل تُرى بثرات الجرافيولا السوداء على أقدم السعف؟",
    ),
    (
        "date_honeydew_seen",
        "Honeydew or sooty fronds",
        "ندوة عسلية أو سعف مسودّ",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Has a scout seen honeydew drops or sooty fronds?",
        "تسأل أشجار المجدول: هل رأى المستكشف قطرات ندوة عسلية أو سعفًا مسودًّا؟",
    ),
    (
        "date_scale_per_leaflet",
        "White scale per leaflet",
        "القشرية البيضاء لكل وريقة",
        "numeric",
        None,
        None,
        "insects per leaflet",
        "حشرة لكل وريقة",
        0,
        10000,
        30,
        "Medjool trees ask: Is the white-scale count per leaflet at or above the action level?",
        "تسأل أشجار المجدول: هل عدد القشرية البيضاء لكل وريقة عند حد التدخل أو أعلى؟",
    ),
    (
        "date_bt_applied",
        "Bt applied at pollination",
        "طُبّق Bt عند التلقيح",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        70,
        "Medjool trees ask: Has Bt been applied at pollination?",
        "تسأل أشجار المجدول: هل طُبّق Bt عند التلقيح؟",
    ),
    (
        "date_dates_in_storage",
        "Dates in storage",
        "تمور في المخزن",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        "Medjool trees ask: Are dates in storage?",
        "تسأل أشجار المجدول: هل توجد تمور في المخزن؟",
    ),
    (
        "date_irrigation_method",
        "Irrigation method",
        "طريقة الري",
        "categorical",
        ["flood", "basin", "drip"],
        ["غمر", "أحواض", "تنقيط"],
        None,
        None,
        None,
        None,
        None,
        "Medjool trees ask: Is the block flood-irrigated?",
        "تسأل أشجار المجدول: هل القطعة تُروى بالغمر؟",
    ),
    (
        "date_drone_crown_temp_anomaly",
        "Drone: abnormal crown temperature",
        "المسيّرة: حرارة تاج غير طبيعية",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Did the drone thermal flight flag palms with abnormal maximum crown temperature or spread?",
        "تسأل أشجار المجدول: هل حددت رحلة المسيّرة الحرارية نخيلًا بأقصى حرارة تاج أو تباين غير طبيعي؟",
    ),
    (
        "date_drone_ndre_no_seasonal_rise",
        "Drone: no seasonal NDRE rise",
        "المسيّرة: لا ارتفاع موسمي في NDRE",
        "boolean",
        None,
        None,
        None,
        None,
        None,
        None,
        30,
        "Medjool trees ask: Did drone NDRE time series flag palms that missed the June–December greenness rise?",  # noqa: RUF001 (verbatim from the trees document)
        "تسأل أشجار المجدول: هل حددت سلاسل NDRE من المسيّرة نخيلًا افتقدت ارتفاع الخضرة يونيو–ديسمبر؟",  # noqa: RUF001
    ),
)

# (code, name_en, name_ar, member codes in form order). `date_ripening_stage`
# is the existing 0098 signal.
TEMPLATES: tuple[tuple, ...] = (
    (
        "medjool_rpw_inspection",
        "RPW inspection (monthly)",
        "فحص سوسة النخيل الحمراء (شهري)",
        [
            "date_rpw_symptom_seen",
            "date_offshoot_or_frond_cut",
            "date_wounds_treated",
            "date_aerial_roots_exposed",
            "date_rodent_damage_seen",
            "date_infested_waste_left",
            "date_rpw_trap_catch_value",
            "date_rpw_inspection_done",
            "date_trap_serviced",
        ],
    ),
    (
        "medjool_bunch_scouting",
        "Bunch scouting (weekly)",
        "فحص العذوق (أسبوعي)",
        [
            "date_mite_webbing_seen",
            "date_hollow_fruit_seen",
            "date_spathe_rot_seen",
            "date_bunches_bagged",
            "date_ripening_stage",
            "date_bunches_scouted",
        ],
    ),
    (
        "medjool_frond_crown_check",
        "Frond and crown check",
        "فحص السعف والتاج",
        [
            "date_charcoal_lesions_seen",
            "date_rachis_one_side_whitening",
            "date_leaf_base_rot_seen",
            "date_yellow_streaking_stunting",
            "date_brittle_leaflets_seen",
            "date_graphiola_spots_seen",
            "date_honeydew_seen",
            "date_scale_per_leaflet",
        ],
    ),
    (
        "medjool_farm_records",
        "Farm records",
        "سجلات المزرعة",
        [
            "date_bt_applied",
            "date_dates_in_storage",
            "date_irrigation_method",
        ],
    ),
    (
        "medjool_drone_results",
        "Drone flight results",
        "نتائج رحلات المسيّرة",
        [
            "date_drone_crown_temp_anomaly",
            "date_drone_ndre_no_seasonal_rise",
        ],
    ),
)

# Rows of public 0098, scoped here so all Medjool signals live in one place.
EXISTING_DEFINITIONS = (
    "date_rpw_trap_catch",
    "date_rpw_infested_palm",
    "date_rpw_palm_removed",
    "date_bunches_pollinated",
    "date_strands_per_bunch",
    "date_fruits_per_strand",
    "date_bunches_per_palm",
    "date_leaves_per_palm",
    "date_dust_mite_found",
    "date_ripening_stage",
    "date_fruit_cracking_seen",
    "date_black_nose_seen",
    "date_harvest_pass",
    "date_new_growth_seen",
    "date_soil_pulled_away",
)
EXISTING_TEMPLATES = ("medjool_bearing", "medjool_new_planting")

_CODES = sa.bindparam("codes", type_=sa.ARRAY(sa.Text()))
_SCOPE = sa.bindparam("scope", type_=sa.ARRAY(sa.Text()))


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
                    aggregation_window_days, crop_paths
                )
                SELECT NULL, :code, :name, :name_ar, :description, :description_ar,
                       :value_kind, :unit, :unit_ar,
                       CAST(:categorical_values AS text[]),
                       CAST(:categorical_values_ar AS text[]),
                       :value_min, :value_max, TRUE, TRUE, 'latest', :window_days,
                       :scope
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.signal_definitions
                     WHERE code = :code AND tenant_id IS NULL
                 )
                """
            ).bindparams(_SCOPE),
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
                "window_days": window_days,
                "scope": SCOPE,
            },
        )

    for template_code, name_en, name_ar, members in TEMPLATES:
        conn.execute(
            sa.text(
                """
                INSERT INTO public.signal_templates
                       (tenant_id, code, name, name_ar, is_active, crop_paths)
                SELECT NULL, :code, :name, :name_ar, TRUE, :scope
                 WHERE NOT EXISTS (
                    SELECT 1 FROM public.signal_templates
                     WHERE code = :code AND tenant_id IS NULL
                 )
                """
            ).bindparams(_SCOPE),
            {"code": template_code, "name": name_en, "name_ar": name_ar, "scope": SCOPE},
        )
        for position, definition_code in enumerate(members):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO public.signal_template_definitions
                           (template_id, signal_definition_id, position, is_required)
                    SELECT t.id, d.id, :position, FALSE
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
                },
            )

    # Scope the 0098 rows, but never overwrite a scope someone set by hand.
    conn.execute(
        sa.text(
            "UPDATE public.signal_definitions SET crop_paths = :scope "
            "WHERE tenant_id IS NULL AND code = ANY(:codes) AND cardinality(crop_paths) = 0"
        ).bindparams(_CODES, _SCOPE),
        {"codes": list(EXISTING_DEFINITIONS), "scope": SCOPE},
    )
    conn.execute(
        sa.text(
            "UPDATE public.signal_templates SET crop_paths = :scope "
            "WHERE tenant_id IS NULL AND code = ANY(:codes) AND cardinality(crop_paths) = 0"
        ).bindparams(_CODES, _SCOPE),
        {"codes": list(EXISTING_TEMPLATES), "scope": SCOPE},
    )


def downgrade() -> None:
    conn = op.get_bind()
    template_codes = [t[0] for t in TEMPLATES]
    definition_codes = [d[0] for d in DEFINITIONS]
    conn.execute(
        sa.text(
            "UPDATE public.signal_definitions SET crop_paths = '{}' "
            "WHERE tenant_id IS NULL AND code = ANY(:codes) AND crop_paths = :scope"
        ).bindparams(_CODES, _SCOPE),
        {"codes": list(EXISTING_DEFINITIONS), "scope": SCOPE},
    )
    conn.execute(
        sa.text(
            "UPDATE public.signal_templates SET crop_paths = '{}' "
            "WHERE tenant_id IS NULL AND code = ANY(:codes) AND crop_paths = :scope"
        ).bindparams(_CODES, _SCOPE),
        {"codes": list(EXISTING_TEMPLATES), "scope": SCOPE},
    )
    conn.execute(
        sa.text(
            "DELETE FROM public.signal_template_definitions WHERE template_id IN ("
            " SELECT id FROM public.signal_templates"
            " WHERE tenant_id IS NULL AND code = ANY(:codes))"
        ).bindparams(_CODES),
        {"codes": template_codes},
    )
    conn.execute(
        sa.text(
            "DELETE FROM public.signal_templates WHERE tenant_id IS NULL AND code = ANY(:codes)"
        ).bindparams(_CODES),
        {"codes": template_codes},
    )
    conn.execute(
        sa.text(
            "DELETE FROM public.signal_definitions WHERE tenant_id IS NULL AND code = ANY(:codes)"
        ).bindparams(_CODES),
        {"codes": definition_codes},
    )
