"""Write the Medjool decision trees and their finding codes as JSON.

Source: Organic Medjool Manual, Edition 1.3, September 2026. Every check
comes from a sentence in the manual; no threshold is invented. The manual
gives no numbers for "low temperature at pollination", "humid weather at
Khalal" or a high weevil catch (and section 13 lists the dust-mite threshold
as not found), so those checks are not built.

The trees read the Medjool scouting signals from public migration 0098. A
tenant must assign those signals to the farm or block, or every signal reads
as missing.

Run from the repository root:

    python scripts/build_medjool_trees.py

It writes docs/trees/medjool/*.definition.json and findings.json, then
compiles each definition with the app's compiler and prints the node count.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "trees" / "medjool"
CROP_PATH = "date_palm.medjool"

FINDINGS: list[dict[str, str]] = [
    {
        "code": "rpw_traps_not_serviced",
        "name_en": "Weevil traps not checked",
        "name_ar": "مصائد السوسة لم تُخدم",
        "clause_en": "no weevil trap record in the last 14 days",
        "clause_ar": "لا يوجد سجل لخدمة مصائد السوسة خلال آخر 14 يومًا",
        "default_status": "issue",
        "description_en": "Manual 10.1: pheromone traps are serviced every 7-14 days and catches are recorded.",
        "description_ar": "الدليل 10.1: تُخدم المصائد الفرمونية كل 7-14 يومًا مع تسجيل أعداد الحشرات الملتقطة.",
    },
    {
        "code": "rpw_infested_palm",
        "name_en": "Weevil-infested palm found",
        "name_ar": "نخلة مصابة بسوسة النخيل الحمراء",
        "clause_en": "a palm infested by red palm weevil was found",
        "clause_ar": "وُجدت نخلة مصابة بسوسة النخيل الحمراء",
        "default_status": "alert",
        "description_en": "Manual 10.1: heavily infested palms are removed and disposed of.",
        "description_ar": "الدليل 10.1: إزالة النخيل شديد الإصابة والتخلص منه.",
    },
    {
        "code": "date_dust_mite",
        "name_en": "Dust mite on bunches",
        "name_ar": "حلم الغبار على العذوق",
        "clause_en": "dust mite was found on the bunches",
        "clause_ar": "وُجد حلم الغبار على العذوق",
        "default_status": "issue",
        "description_en": "Manual 10.3: augmentative release of the predator Stethorus gilvifrons.",
        "description_ar": "الدليل 10.3: المكافحة الحيوية التعزيزية بإطلاق المفترس Stethorus gilvifrons.",
    },
    {
        "code": "date_fruit_cracking",
        "name_en": "Fruit cracking",
        "name_ar": "تشقق الثمار",
        "clause_en": "fruit cracking was seen during ripening",
        "clause_ar": "ظهر تشقق في الثمار أثناء النضج",
        "default_status": "issue",
        "description_en": "Manual 9.6: abrupt changes in soil moisture are a main cause of cracking.",
        "description_ar": "الدليل 9.6: التغيرات المفاجئة في رطوبة التربة وامتلاء الثمار من الأسباب الرئيسية لتشقق الثمار.",
    },
    {
        "code": "date_black_nose",
        "name_en": "Black nose",
        "name_ar": "الذنب الأسود",
        "clause_en": "black nose was seen on the fruit",
        "clause_ar": "ظهر الذنب الأسود على الثمار",
        "default_status": "issue",
        "description_en": "Manual 9.4: mainly caused by humid weather at Khalal.",
        "description_ar": "الدليل 9.4: ينتج أساسًا عن الطقس الرطب في طور الخلال.",
    },
    {
        "code": "pollination_not_recorded",
        "name_en": "Pollination not recorded",
        "name_ar": "التلقيح غير مسجّل",
        "clause_en": "no pollinated bunches were recorded in the last 60 days",
        "clause_ar": "لم تُسجَّل عذوق ملقحة خلال آخر 60 يومًا",
        "default_status": "issue",
        "description_en": "Manual 12.1: record each bunch's pollination date and count thinning and bagging from it.",
        "description_ar": "الدليل 12.1: سجّل تاريخ تلقيح كل عذق واحسب منه مواعيد الخفّ والتكييس.",
    },
]


def _signal(code: str, key: str) -> dict[str, Any]:
    return {"source": "signals", "code": code, "key": key}


def _is_true(code: str) -> dict[str, Any]:
    return {"tree": {"op": "eq", "left": _signal(code, "value_boolean"), "right": True}}


def _stage_in(stages: list[str]) -> dict[str, Any]:
    return {
        "tree": {
            "op": "in",
            "left": {"source": "block", "field": "growth_stage"},
            "values": stages,
        }
    }


def _register(
    code: str, severity: str, label_en: str, label_ar: str, nxt: str
) -> dict[str, Any]:
    return {
        "label_en": label_en,
        "label_ar": label_ar,
        "register": {"code": code, "severity": severity},
        "next": nxt,
    }


_STOP = {"label_en": "End of the walk", "label_ar": "نهاية المسار", "stop": True}


def _tree(
    code: str,
    name_en: str,
    name_ar: str,
    desc_en: str,
    desc_ar: str,
    root: str,
    registers: list[str],
    nodes: dict[str, Any],
    combinations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "code": code,
        "name_en": name_en,
        "name_ar": name_ar,
        "description_en": desc_en,
        "description_ar": desc_ar,
        "scope": "block",
        "crop_path": CROP_PATH,
        "country_codes": ["EG"],
        "root": root,
        "registers": registers,
        "parameters": {},
        "nodes": {**nodes, "n_stop": _STOP},
        "combinations": combinations,
    }


RED_PALM_WEEVIL = _tree(
    "medjool_red_palm_weevil",
    "Medjool — red palm weevil",
    "المجدول — سوسة النخيل الحمراء",
    "Manual 10.1: pheromone traps are serviced every 7-14 days and catches recorded; heavily "
    "infested palms are removed and disposed of. Reads the Medjool scouting signals.",
    "الدليل 10.1: تُخدم المصائد الفرمونية كل 7-14 يومًا مع تسجيل أعداد الحشرات الملتقطة، ويُزال النخيل شديد "
    "الإصابة ويُتخلص منه. تقرأ إشارات استكشاف المجدول.",
    "n_traps",
    ["rpw_traps_not_serviced", "rpw_infested_palm"],
    {
        "n_traps": {
            "label_en": "Was a weevil trap record made in the last 14 days?",
            "label_ar": "هل سُجّلت خدمة لمصائد السوسة خلال آخر 14 يومًا؟",
            "condition": {
                "tree": {
                    "op": "ge",
                    "left": _signal("date_rpw_trap_catch", "value_numeric"),
                    "right": 1,
                }
            },
            "on_match": "n_infested",
            "on_miss": "n_reg_traps",
        },
        "n_reg_traps": _register(
            "rpw_traps_not_serviced",
            "warning",
            "No trap record in 14 days",
            "لا يوجد سجل للمصائد خلال 14 يومًا",
            "n_infested",
        ),
        "n_infested": {
            "label_en": "Was an infested palm found?",
            "label_ar": "هل وُجدت نخلة مصابة؟",
            "condition": _is_true("date_rpw_infested_palm"),
            "on_match": "n_reg_infested",
            "on_miss": "n_stop",
        },
        "n_reg_infested": _register(
            "rpw_infested_palm",
            "critical",
            "An infested palm was found",
            "وُجدت نخلة مصابة",
            "n_stop",
        ),
    },
    [
        {
            "code": "rpw_traps_due",
            "codes": ["rpw_traps_not_serviced"],
            "status": "issue",
            "action_type": "scout",
            "text_en": "No red palm weevil trap record in the last 14 days. Service each pheromone trap - change the food bait and water - and record its catch. The manual says every 7-14 days, all year (section 10.1).",
            "text_ar": "لا يوجد سجل لخدمة مصائد سوسة النخيل الحمراء خلال آخر 14 يومًا. اخدم كل مصيدة فرمونية بتغيير الطعم الغذائي والماء وسجّل أعداد الحشرات الملتقطة. يقول الدليل كل 7-14 يومًا طوال العام (القسم 10.1).",
        },
        {
            "code": "rpw_infested",
            "codes": ["rpw_infested_palm"],
            "status": "alert",
            "action_type": "other",
            "text_en": "A palm infested by red palm weevil was found. The manual says heavily infested palms are removed and disposed of (section 10.1). Record No on the signal once the palm is removed.",
            "text_ar": "وُجدت نخلة مصابة بسوسة النخيل الحمراء. يقول الدليل بإزالة النخيل شديد الإصابة والتخلص منه (القسم 10.1). سجّل «لا» على الإشارة بعد إزالة النخلة.",
        },
        {
            "code": "rpw_infested_and_traps_due",
            "codes": ["rpw_traps_not_serviced", "rpw_infested_palm"],
            "status": "alert",
            "action_type": "other",
            "text_en": "A weevil-infested palm was found and no trap record was made in 14 days. Remove and dispose of heavily infested palms, and service the pheromone traps every 7-14 days (section 10.1).",
            "text_ar": "وُجدت نخلة مصابة بالسوسة ولم تُسجَّل خدمة للمصائد خلال 14 يومًا. أزل النخيل شديد الإصابة وتخلّص منه واخدم المصائد الفرمونية كل 7-14 يومًا (القسم 10.1).",
        },
    ],
)

BUNCH_HEALTH = _tree(
    "medjool_bunch_health",
    "Medjool — bunch health",
    "المجدول — صحة العذوق",
    "Manual 9.4, 9.6 and 10.3: dust mite on bunches, and fruit cracking and black nose during "
    "Khalal, Rutab and Tamar. Reads the Medjool scouting signals. The manual gives no dust-mite "
    "threshold (section 13), so any record of the mite counts.",
    "الدليل 9.4 و9.6 و10.3: حلم الغبار على العذوق، وتشقق الثمار والذنب الأسود في الخلال والرطب "
    "والتمر. لم يُعثر على حدود تدخل لحلم الغبار (القسم 13).",
    "n_mite",
    ["date_dust_mite", "date_fruit_cracking", "date_black_nose"],
    {
        "n_mite": {
            "label_en": "Was dust mite found on the bunches?",
            "label_ar": "هل وُجد حلم الغبار على العذوق؟",
            "condition": _is_true("date_dust_mite_found"),
            "on_match": "n_reg_mite",
            "on_miss": "n_ripening",
        },
        "n_reg_mite": _register(
            "date_dust_mite",
            "warning",
            "Dust mite found",
            "وُجد حلم الغبار",
            "n_ripening",
        ),
        "n_ripening": {
            "label_en": "Is the block in Khalal, Rutab or Tamar?",
            "label_ar": "هل القطعة في الخلال أو الرطب أو التمر؟",
            "condition": _stage_in(["khalal", "rutab", "tamar"]),
            "on_match": "n_crack",
            "on_miss": "n_stop",
        },
        "n_crack": {
            "label_en": "Was fruit cracking seen?",
            "label_ar": "هل ظهر تشقق في الثمار؟",
            "condition": _is_true("date_fruit_cracking_seen"),
            "on_match": "n_reg_crack",
            "on_miss": "n_black",
        },
        "n_reg_crack": _register(
            "date_fruit_cracking",
            "warning",
            "Fruit cracking seen",
            "ظهر تشقق الثمار",
            "n_black",
        ),
        "n_black": {
            "label_en": "Was black nose seen?",
            "label_ar": "هل ظهر الذنب الأسود؟",
            "condition": _is_true("date_black_nose_seen"),
            "on_match": "n_reg_black",
            "on_miss": "n_stop",
        },
        "n_reg_black": _register(
            "date_black_nose",
            "warning",
            "Black nose seen",
            "ظهر الذنب الأسود",
            "n_stop",
        ),
    },
    [
        {
            "code": "bunch_dust_mite",
            "codes": ["date_dust_mite"],
            "status": "issue",
            "action_type": "other",
            "text_en": "Dust mite was found on the bunches. The manual's biological option is to release the predator Stethorus gilvifrons (section 10.3). Check it against the certifying body's list of permitted inputs first.",
            "text_ar": "وُجد حلم الغبار على العذوق. الخيار الحيوي في الدليل هو المكافحة الحيوية التعزيزية بإطلاق المفترس Stethorus gilvifrons (القسم 10.3). تحقق منه أولًا مقابل قائمة المدخلات المسموح بها لدى جهة الاعتماد.",
        },
        {
            "code": "bunch_cracking",
            "codes": ["date_fruit_cracking"],
            "status": "issue",
            "action_type": "irrigate",
            "text_en": "Fruit cracking was seen during ripening. Abrupt changes in soil moisture are a main cause. Keep soil moisture steady with drip through Khalal, Rutab and Tamar (sections 9.6 and 12.2).",
            "text_ar": "ظهر تشقق في الثمار أثناء النضج. التغيرات المفاجئة في رطوبة التربة من الأسباب الرئيسية لتشقق الثمار. حافظ على رطوبة تربة ثابتة بالري بالتنقيط خلال الخلال والرطب والتمر (القسمان 9.6 و12.2).",
        },
        {
            "code": "bunch_black_nose",
            "codes": ["date_black_nose"],
            "status": "issue",
            "action_type": "other",
            "text_en": "Black nose was seen on the fruit. It is mainly caused by humid weather at Khalal. Bagging with brown wrapping paper was reported to inhibit it (section 9.4).",
            "text_ar": "ظهر الذنب الأسود على الثمار. ينتج أساسًا عن الطقس الرطب في طور الخلال، وأُفيد بأن التكييس بورق التغليف البني يحدّ منه (القسم 9.4).",
        },
    ],
)

POLLINATION_RECORD = _tree(
    "medjool_pollination_record",
    "Medjool — pollination record",
    "المجدول — سجل التلقيح",
    "Manual 12.1: record each bunch's pollination date and count thinning and bagging from it. "
    "During late pollination and Hababouk this checks that pollinated bunches were recorded.",
    "الدليل 12.1: سجّل تاريخ تلقيح كل عذق واحسب منه مواعيد الخفّ والتكييس. تتحقق هذه الشجرة في مرحلة آخر "
    "التلقيح والحبابوك من تسجيل العذوق الملقحة.",
    "n_stage",
    ["pollination_not_recorded"],
    {
        "n_stage": {
            "label_en": "Is the block in late pollination or Hababouk?",
            "label_ar": "هل القطعة في مرحلة آخر التلقيح والحبابوك؟",
            "condition": _stage_in(["fruit_set"]),
            "on_match": "n_recorded",
            "on_miss": "n_stop",
        },
        "n_recorded": {
            "label_en": "Were pollinated bunches recorded in the last 60 days?",
            "label_ar": "هل سُجّلت عذوق ملقحة خلال آخر 60 يومًا؟",
            "condition": {
                "tree": {
                    "op": "gt",
                    "left": _signal("date_bunches_pollinated", "value_numeric"),
                    "right": 0,
                }
            },
            "on_match": "n_stop",
            "on_miss": "n_reg_missing",
        },
        "n_reg_missing": _register(
            "pollination_not_recorded",
            "warning",
            "No pollination recorded",
            "لم يُسجَّل تلقيح",
            "n_stop",
        ),
    },
    [
        {
            "code": "pollination_record_missing",
            "codes": ["pollination_not_recorded"],
            "status": "issue",
            "action_type": "scout",
            "text_en": "No pollinated bunches were recorded in the last 60 days. Record the pollination date of each bunch: hand thinning is due 3-4 weeks after pollination and bagging at the start of Khalal (sections 9.2 and 12.1).",
            "text_ar": "لم تُسجَّل عذوق ملقّحة خلال آخر 60 يومًا. سجّل تاريخ تلقيح كل عذق: يُجرى الخفّ اليدوي بعد 3-4 أسابيع من التلقيح والتكييس في بداية طور الخلال (القسمان 9.2 و12.1).",
        },
    ],
)

TREES = [RED_PALM_WEEVIL, BUNCH_HEALTH, POLLINATION_RECORD]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "findings.json").write_text(
        json.dumps(FINDINGS, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for tree in TREES:
        (OUT / f"{tree['code']}.definition.json").write_text(
            json.dumps(tree, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    sys.path.insert(0, str(ROOT / "backend"))
    from app.modules.recommendations.folding_compiler import compile_folding_tree

    known = {f["code"] for f in FINDINGS}
    for tree in TREES:
        compiled = compile_folding_tree(tree, known_codes=known)
        print(
            f"{tree['code']}: {len(tree['nodes'])} nodes, compiled code={compiled['code']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
