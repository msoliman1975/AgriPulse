"""Build the seven mango folding trees and the finding codes they need.

The 31 mango trees written in the old designer each ask one question about
one index and open one card. This script writes the seven trees that replace
them, grouped by agronomy problem area, in the shape the folding compiler
takes: `set` nodes load the band for the recorded tree size, `condition`
nodes ask one question, `register` nodes record a finding and carry on, and
one `stop` node per tree folds the findings into a single card.

The design is docs/proposals/mango-tree-regrouping.html. Every band and
threshold here is copied from the old tree that owned it, read from
production on 2026-09-21, so no number is re-authored:

    t_ndmi_leaf_water, t_smi_soil_moisture, t_cwsi_irrigation_stress,
    t_deficit_irrigation_verify, t_msavi/savi/ndvi_canopy_vigour,
    t_gndvi_chlorophyll, t_ndre_nitrogen, t_bsi_ground_cover,
    t_size_record_check, t_anthracnose_mealybug_watch, t_bloom_protection,
    t_fruit_fly_harvest_readiness, t_flower_induction_readiness,
    mango_stress_induction_v1.

Two shapes are deliberate and are worth knowing before reading the graphs.

**A `switch` errors the whole walk when its subject reads as nothing.** The
engine treats `default` as the branch for a value the cases did not cover,
not as a hiding place for a value that was never read. So a switch is used
only for a weather risk score behind a stage gate, exactly as `mango_unified`
does it, and every crop attribute or growth stage is asked with a
`condition`, whose `on_miss` is a real branch.

**A combination rule matches the finding set of one walk, exactly.** So the
graphs are written to keep the set of reachable finding sets small and
enumerable, and `rules_for` below lists one rule per set a walk can produce.
A set with no rule folds to the tree's default card.

Writes to docs/trees/mango_seven/. Nothing here talks to the API;
scripts/create-mango-seven.ps1 posts what this writes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parent.parent / "docs" / "trees" / "mango_seven"

# ---------------------------------------------------------------------
# Value references. One helper per `source` the evaluator resolves.
# ---------------------------------------------------------------------


def idx(code: str, key: str = "mean") -> dict[str, Any]:
    return {"source": "indices", "index_code": code, "key": key}


def param(name: str) -> dict[str, Any]:
    return {"source": "params", "name": name}


def var(name: str) -> dict[str, Any]:
    return {"source": "vars", "name": name}


def attr(code: str) -> dict[str, Any]:
    return {"source": "crop_attribute", "code": code, "key": "value"}


STAGE = {"source": "block", "field": "growth_stage"}


def risk(code: str) -> dict[str, Any]:
    return {"source": "weather_risk", "risk_code": code, "field": "score"}


def forecast(field: str) -> dict[str, Any]:
    return {"source": "weather", "scope": "forecast_72h", "field": field}


# ---------------------------------------------------------------------
# Node builders
# ---------------------------------------------------------------------


def cond(en: str, ar: str, tree: dict[str, Any], on_match: str, on_miss: str) -> dict[str, Any]:
    return {
        "label_en": en,
        "label_ar": ar,
        "condition": {"tree": tree},
        "on_match": on_match,
        "on_miss": on_miss,
    }


def setter(en: str, ar: str, values: dict[str, Any], nxt: str) -> dict[str, Any]:
    return {"label_en": en, "label_ar": ar, "set": values, "next": nxt}


def register(en: str, ar: str, code: str, severity: str, nxt: str) -> dict[str, Any]:
    return {
        "label_en": en,
        "label_ar": ar,
        "register": {"code": code, "severity": severity},
        "next": nxt,
    }


STOP = {"label_en": "End of the walk", "label_ar": "نهاية المسار", "stop": True}


def op(operator: str, left: Any, right: Any) -> dict[str, Any]:
    return {"op": operator, "left": left, "right": right}


def op_in(left: Any, values: list[str]) -> dict[str, Any]:
    return {"op": "in", "left": left, "values": values}


def rule(
    codes: list[str], status: str, action: str, en: str, ar: str, code: str
) -> dict[str, Any]:
    return {
        "code": code,
        "codes": sorted(set(codes)),
        "status": status,
        "action_type": action,
        "text_en": en,
        "text_ar": ar,
    }


def number(default: float, low: float, high: float) -> dict[str, Any]:
    return {"type": "number", "default": default, "min": low, "max": high}


# The three size branches every band-reading tree opens with. `miss` is where
# a block with no recorded size goes: the size_missing register, never a
# switch default, because the attribute is the thing most often absent.
def size_gate(bands: dict[str, str], miss: str) -> dict[str, Any]:
    return {
        "n_size_small": cond(
            "Is the block recorded as small trees?",
            "هل القطعة مسجّلة كأشجار صغيرة؟",
            op("eq", attr("tree_size_class"), "small"),
            bands["small"],
            "n_size_medium",
        ),
        "n_size_medium": cond(
            "Is the block recorded as medium trees?",
            "هل القطعة مسجّلة كأشجار متوسطة؟",
            op("eq", attr("tree_size_class"), "medium"),
            bands["medium"],
            "n_size_large",
        ),
        "n_size_large": cond(
            "Is the block recorded as large trees?",
            "هل القطعة مسجّلة كأشجار كبيرة؟",
            op("eq", attr("tree_size_class"), "large"),
            bands["large"],
            miss,
        ),
    }


# ---------------------------------------------------------------------
# 1. mango_water
# ---------------------------------------------------------------------


def build_water() -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    nodes.update(
        size_gate(
            {"small": "n_bands_small", "medium": "n_bands_medium", "large": "n_bands_large"},
            "n_reg_size_missing",
        )
    )
    for size, ar_size in (("small", "الصغيرة"), ("medium", "المتوسطة"), ("large", "الكبيرة")):
        nodes[f"n_bands_{size}"] = setter(
            f"Load the {size}-tree water bands",
            f"حمّل نطاقات المياه للأشجار {ar_size}",
            {
                "size_class": size,
                "ndmi_floor": param(f"{size}_ndmi_floor"),
                "smi_floor": param(f"{size}_smi_floor"),
                "smi_deficit_floor": param(f"{size}_smi_deficit_floor"),
                "cwsi_ceiling": param(f"{size}_cwsi_ceiling"),
            },
            "n_deficit_gate",
        )
    nodes["n_reg_size_missing"] = register(
        "No tree size is recorded, so no band could be checked",
        "لا يوجد حجم شجرة مسجّل، فلا يمكن فحص أي نطاق",
        "size_missing",
        "info",
        "n_stop",
    )

    nodes["n_deficit_gate"] = cond(
        "Is this a bearing block inside the pre-harvest maturity window?",
        "هل هذه قطعة مثمرة داخل نافذة النضج قبل الحصاد؟",
        {
            "all_of": [
                op("eq", attr("bearing_status"), "bearing"),
                op_in(STAGE, ["maturation"]),
            ]
        },
        "n_deficit_overshot",
        "n_leaf_water",
    )
    nodes["n_deficit_overshot"] = cond(
        "Has soil moisture fallen below the deficit band?",
        "هل هبطت رطوبة التربة دون نطاق التعطيش؟",
        op("lt", idx("smi"), var("smi_deficit_floor")),
        "n_reg_deficit_overshot",
        "n_deficit_confirmed",
    )
    nodes["n_reg_deficit_overshot"] = register(
        "The pre-harvest cut went deeper than intended",
        "تجاوز خفض الريّ قبل الحصاد الحدّ المقصود",
        "deficit_overshot",
        "critical",
        "n_stop",
    )
    nodes["n_deficit_confirmed"] = cond(
        "Is soil moisture inside the reduced band the cut should produce?",
        "هل رطوبة التربة داخل النطاق المخفّض الذي يفترض أن يُنتجه الخفض؟",
        op("lt", idx("smi"), var("smi_floor")),
        "n_reg_deficit_confirmed",
        "n_reg_deficit_missing",
    )
    nodes["n_reg_deficit_confirmed"] = register(
        "The pre-harvest cut is on plan",
        "خفض الريّ قبل الحصاد يسير على الخطة",
        "deficit_confirmed",
        "info",
        "n_stop",
    )
    nodes["n_reg_deficit_missing"] = register(
        "The pre-harvest cut has not happened",
        "لم يحدث خفض الريّ قبل الحصاد",
        "deficit_missing",
        "warning",
        "n_stop",
    )

    nodes["n_leaf_water"] = cond(
        "Is leaf water below the band for this tree size?",
        "هل ماء الأوراق دون النطاق لهذا الحجم؟",
        op("le", idx("ndmi"), var("ndmi_floor")),
        "n_reg_dry",
        "n_soil_water",
    )
    nodes["n_reg_dry"] = register(
        "Leaf water is low", "ماء الأوراق منخفض", "dry", "warning", "n_soil_water"
    )
    nodes["n_soil_water"] = cond(
        "Is soil moisture below the band for this tree size?",
        "هل رطوبة التربة دون النطاق لهذا الحجم؟",
        op("lt", idx("smi"), var("smi_floor")),
        "n_reg_soil_dry",
        "n_cwsi_guard",
    )
    nodes["n_reg_soil_dry"] = register(
        "Soil moisture is below the band",
        "رطوبة التربة دون النطاق",
        "soil_dry",
        "warning",
        "n_cwsi_guard",
    )
    # A CWSI pinned at its ceiling is a clipped reading, not a hot canopy.
    # t_water_stress_confirm drops the thermal vote in that case and so does
    # this: a clipped value would otherwise turn every cell into an alert.
    nodes["n_cwsi_guard"] = cond(
        "Is the thermal reading clipped at its ceiling?",
        "هل القراءة الحرارية مثبّتة عند سقفها؟",
        op("ge", idx("cwsi"), param("saturation_guard")),
        "n_stop",
        "n_canopy_temp",
    )
    nodes["n_canopy_temp"] = cond(
        "Is the canopy hotter than the band for this tree size?",
        "هل المجموع الخضري أسخن من النطاق لهذا الحجم؟",
        op("ge", idx("cwsi"), var("cwsi_ceiling")),
        "n_reg_canopy_hot",
        "n_stop",
    )
    nodes["n_reg_canopy_hot"] = register(
        "The canopy is warmer than the air by more than usual",
        "المجموع الخضري أسخن من الهواء بأكثر من المعتاد",
        "canopy_hot",
        "warning",
        "n_stop",
    )
    nodes["n_stop"] = dict(STOP)

    parameters = {
        "small_ndmi_floor": number(-0.15, -1.0, 1.0),
        "medium_ndmi_floor": number(0.0, -1.0, 1.0),
        "large_ndmi_floor": number(0.11, -1.0, 1.0),
        "small_smi_floor": number(0.35, 0.0, 1.0),
        "medium_smi_floor": number(0.4, 0.0, 1.0),
        "large_smi_floor": number(0.45, 0.0, 1.0),
        "small_smi_deficit_floor": number(0.27, 0.0, 1.0),
        "medium_smi_deficit_floor": number(0.31, 0.0, 1.0),
        "large_smi_deficit_floor": number(0.35, 0.0, 1.0),
        "small_cwsi_ceiling": number(0.35, 0.0, 1.0),
        "medium_cwsi_ceiling": number(0.3, 0.0, 1.0),
        "large_cwsi_ceiling": number(0.25, 0.0, 1.0),
        "saturation_guard": number(0.99, 0.0, 1.0),
    }

    combos = [
        rule(
            ["dry", "soil_dry", "canopy_hot"],
            "alert",
            "irrigate",
            "All three water readings agree that this cell is short of water: leaf water, "
            "soil moisture and canopy temperature. Irrigate. Check the line and the emitters "
            "while you are there.",
            "القراءات الثلاث كلها تتفق على أن هذه الخلية تنقصها المياه: ماء الأوراق ورطوبة "
            "التربة وحرارة المجموع. ارْوِ القطعة، وافحص الخط والنقاطات أثناء ذلك.",
            "water_all_three",
        ),
        rule(
            ["dry", "soil_dry"],
            "alert",
            "irrigate",
            "Leaf water and soil moisture both read short for this tree size. Irrigate.",
            "ماء الأوراق ورطوبة التربة كلاهما دون المطلوب لهذا الحجم. ارْوِ القطعة.",
            "water_leaf_soil",
        ),
        rule(
            ["dry", "canopy_hot"],
            "alert",
            "irrigate",
            "Leaf water is low and the canopy is running hot. Irrigate.",
            "ماء الأوراق منخفض والمجموع الخضري ساخن. ارْوِ القطعة.",
            "water_leaf_thermal",
        ),
        rule(
            ["soil_dry", "canopy_hot"],
            "alert",
            "irrigate",
            "Soil moisture is below the band and the canopy is running hot. Irrigate.",
            "رطوبة التربة دون النطاق والمجموع الخضري ساخن. ارْوِ القطعة.",
            "water_soil_thermal",
        ),
        rule(
            ["dry"],
            "issue",
            "no_action",
            "Leaf water is low, and the soil and thermal readings do not agree. Watch this "
            "cell on the next pass before changing the schedule.",
            "ماء الأوراق منخفض، ولا تتفق معه قراءتا التربة والحرارة. راقب هذه الخلية في "
            "المرور القادم قبل تغيير برنامج الريّ.",
            "water_leaf_only",
        ),
        rule(
            ["soil_dry"],
            "issue",
            "no_action",
            "Soil moisture is below the band, and the leaf and thermal readings do not agree. "
            "Watch this cell on the next pass.",
            "رطوبة التربة دون النطاق، ولا تتفق معها قراءتا الأوراق والحرارة. راقب هذه الخلية "
            "في المرور القادم.",
            "water_soil_only",
        ),
        rule(
            ["canopy_hot"],
            "issue",
            "no_action",
            "The canopy is warmer than usual, and neither water reading agrees. Watch this "
            "cell on the next pass.",
            "المجموع الخضري أسخن من المعتاد، ولا تتفق معه أي من قراءتي المياه. راقب هذه "
            "الخلية في المرور القادم.",
            "water_thermal_only",
        ),
        rule(
            ["deficit_confirmed"],
            "good",
            "no_action",
            "Soil moisture has fallen into the reduced band that pre-harvest deficit "
            "irrigation is meant to produce. Hold the current schedule.",
            "هبطت رطوبة التربة إلى النطاق المخفّض المقصود من تعطيش ما قبل الحصاد. حافظ على "
            "البرنامج الحالي.",
            "deficit_on_plan",
        ),
        rule(
            ["deficit_missing"],
            "issue",
            "irrigate",
            "The block is in its maturity window and soil moisture is still at the full "
            "irrigation level. Cut the water now, or fruit sugars and colour will lag.",
            "القطعة في نافذة النضج ورطوبة التربة ما زالت عند مستوى الريّ الكامل. اخفض المياه "
            "الآن وإلا تأخّرت السكريات واللون.",
            "deficit_not_done",
        ),
        rule(
            ["deficit_overshot"],
            "alert",
            "irrigate",
            "The pre-harvest cut has gone deeper than intended and is now costing fruit size. "
            "Give one recovery irrigation and return to the deficit band.",
            "تجاوز خفض ما قبل الحصاد الحدّ المقصود وصار يكلّف حجم الثمار. أعطِ ريّة تعويضية "
            "واحدة ثم عُد إلى نطاق التعطيش.",
            "deficit_too_deep",
        ),
        rule(
            ["size_missing"],
            "na",
            "no_action",
            "No tree size is recorded for this block, so no water band could be checked. Set "
            "the Tree size attribute on the crop assignment.",
            "لا يوجد حجم شجرة مسجّل لهذه القطعة، فلم يمكن فحص أي نطاق مياه. اضبط خاصية حجم "
            "الشجرة على تخصيص المحصول.",
            "water_size_missing",
        ),
    ]

    return {
        "code": "mango_water",
        "name_en": "Mango — water and irrigation",
        "name_ar": "المانجو — المياه والريّ",
        "description_en": (
            "Is this cell short of water, and is the pre-harvest cut on plan? Reads leaf "
            "water, soil moisture and canopy temperature against the band the mango index "
            "guide gives for the block's recorded tree size, and registers one finding for "
            "each reading that is short. The fold turns agreement into severity, so one "
            "reading alone never opens an irrigation card. In the maturity window on a "
            "bearing block it asks the deficit question instead."
        ),
        "description_ar": (
            "هل تنقص هذه الخلية مياه، وهل يسير خفض ما قبل الحصاد على الخطة؟ يقرأ ماء الأوراق "
            "ورطوبة التربة وحرارة المجموع مقابل النطاق الذي يعطيه دليل مؤشرات المانجو لحجم "
            "الشجرة المسجّل، ويسجّل نتيجة لكل قراءة ناقصة. يحوّل الدمج الاتفاق إلى درجة خطورة، "
            "فلا تفتح قراءة واحدة بطاقة ريّ وحدها. وفي نافذة النضج على قطعة مثمرة يسأل سؤال "
            "التعطيش بدلاً من ذلك."
        ),
        "scope": "cell",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_size_small",
        "registers": [
            "dry",
            "soil_dry",
            "canopy_hot",
            "deficit_confirmed",
            "deficit_missing",
            "deficit_overshot",
            "size_missing",
        ],
        "parameters": parameters,
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# 2. mango_canopy_and_stand
# ---------------------------------------------------------------------


def build_canopy() -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    nodes.update(
        size_gate(
            {"small": "n_bands_small", "medium": "n_bands_medium", "large": "n_bands_large"},
            "n_reg_size_missing",
        )
    )
    # One vigour index per size, as the guide recommends: the soil-corrected
    # form on young trees where most of the pixel is bare ground, and plain
    # NDVI once the canopy has closed. `vigour_flag` is written here on every
    # branch so the later read of it is definitely set on every path.
    for size, index_code, ar_size in (
        ("small", "msavi", "الصغيرة"),
        ("medium", "savi", "المتوسطة"),
        ("large", "ndvi", "الكبيرة"),
    ):
        nodes[f"n_bands_{size}"] = setter(
            f"Load the {size}-tree bands and read {index_code.upper()}",
            f"حمّل نطاقات الأشجار {ar_size} واقرأ {index_code.upper()}",
            {
                "size_class": size,
                "index_used": index_code,
                "vigour_now": idx(index_code),
                "vigour_z": idx(index_code, "baseline_deviation"),
                "vigour_floor": param(f"{size}_{index_code}_floor"),
                "bsi_now": idx("bsi"),
                "bsi_ceiling": param(f"{size}_bsi_ceiling"),
                "vigour_flag": "ok",
            },
            "n_vigour_check",
        )
    nodes["n_reg_size_missing"] = register(
        "No tree size is recorded, so no band could be checked",
        "لا يوجد حجم شجرة مسجّل، فلا يمكن فحص أي نطاق",
        "size_missing",
        "info",
        "n_stop",
    )

    nodes["n_vigour_check"] = cond(
        "Is canopy vigour below the band for this tree size?",
        "هل حيوية المجموع دون النطاق لهذا الحجم؟",
        op("le", var("vigour_now"), var("vigour_floor")),
        "n_reg_vigour_low",
        "n_decline_check",
    )
    nodes["n_reg_vigour_low"] = register(
        "Canopy vigour is below the band for this tree size",
        "حيوية المجموع دون النطاق لهذا الحجم",
        "vigour_low",
        "warning",
        "n_mark_low",
    )
    nodes["n_mark_low"] = setter(
        "Remember that vigour read low",
        "سجّل أن الحيوية جاءت منخفضة",
        {"vigour_flag": "low"},
        "n_decline_check",
    )
    nodes["n_decline_check"] = cond(
        "Has the block fallen below its own history for this day of year?",
        "هل هبطت القطعة دون تاريخها لهذا اليوم من السنة؟",
        op("le", var("vigour_z"), param("vigour_drop_z")),
        "n_reg_declining",
        "n_cover_check",
    )
    nodes["n_reg_declining"] = register(
        "The block as a whole is below its seasonal baseline",
        "القطعة ككل دون خط أساسها الموسمي",
        "block_declining",
        "warning",
        "n_both_gate",
    )
    # The cause split runs only when both the band and the block's own history
    # say the canopy is weak. One weak signal is a watch, not a diagnosis, and
    # naming a cause from it would put a wrong reason on the card.
    nodes["n_both_gate"] = cond(
        "Is vigour weak against the band as well as against the block's history?",
        "هل الحيوية ضعيفة مقابل النطاق وتاريخ القطعة معًا؟",
        op("eq", var("vigour_flag"), "low"),
        "n_cause_cover",
        "n_cover_check",
    )
    nodes["n_cause_cover"] = cond(
        "Has more bare ground appeared between the trees?",
        "هل ظهرت أرض عارية أكثر بين الأشجار؟",
        op("ge", var("bsi_now"), var("bsi_ceiling")),
        "n_reg_cover_open",
        "n_cause_dry",
    )
    nodes["n_cause_dry"] = cond(
        "Is leaf water below normal for this block at this time of year?",
        "هل ماء الأوراق دون المعتاد لهذه القطعة في هذا الوقت؟",
        op("le", idx("ndmi", "baseline_deviation"), param("dry_z")),
        "n_reg_dry",
        "n_cause_nutrient",
    )
    nodes["n_reg_dry"] = register(
        "Leaf water is low", "ماء الأوراق منخفض", "dry", "warning", "n_cause_nutrient"
    )
    nodes["n_cause_nutrient"] = cond(
        "Is red-edge below normal for this block at this time of year?",
        "هل الحافة الحمراء دون المعتاد لهذه القطعة في هذا الوقت؟",
        op("le", idx("ndre", "baseline_deviation"), param("low_ndre_z")),
        "n_reg_nutrient",
        "n_stop",
    )
    nodes["n_reg_nutrient"] = register(
        "Leaf nitrogen is below the band",
        "نيتروجين الأوراق دون النطاق",
        "nutrient_low",
        "warning",
        "n_stop",
    )
    nodes["n_cover_check"] = cond(
        "Is more bare ground showing than the guide expects for this size?",
        "هل الأرض العارية أكثر مما يتوقعه الدليل لهذا الحجم؟",
        op("ge", var("bsi_now"), var("bsi_ceiling")),
        "n_reg_cover_open",
        "n_stop",
    )
    nodes["n_reg_cover_open"] = register(
        "More bare ground is showing than the guide expects",
        "الأرض العارية أكثر مما يتوقعه الدليل",
        "cover_open",
        "warning",
        "n_stop",
    )
    nodes["n_stop"] = dict(STOP)

    parameters = {
        "small_msavi_floor": number(0.15, -1.0, 1.0),
        "medium_savi_floor": number(0.28, -1.0, 1.0),
        "large_ndvi_floor": number(0.65, -1.0, 1.0),
        "small_bsi_ceiling": number(0.55, -1.0, 1.0),
        "medium_bsi_ceiling": number(0.3, -1.0, 1.0),
        "large_bsi_ceiling": number(0.14, -1.0, 1.0),
        "vigour_drop_z": number(-1.0, -5.0, 0.0),
        "dry_z": number(-1.0, -5.0, 0.0),
        "low_ndre_z": number(-1.0, -5.0, 0.0),
    }

    combos = [
        rule(
            ["vigour_low", "block_declining", "cover_open"],
            "alert",
            "scout",
            "The canopy is weak and more bare ground is showing at the same time. That points "
            "at missing, failed or removed trees rather than at the health of the trees still "
            "standing. Walk the rows and count the gaps.",
            "المجموع ضعيف وظهرت أرض عارية أكثر في الوقت نفسه. هذا يشير إلى أشجار مفقودة أو "
            "فاشلة أو مقلوعة، لا إلى صحة الأشجار القائمة. امشِ بين الصفوف وعُدّ الفجوات.",
            "canopy_missing_trees",
        ),
        rule(
            ["vigour_low", "block_declining", "dry"],
            "alert",
            "irrigate",
            "The canopy is weak against its band and its own history, and leaf water is below "
            "normal. Water shortage is the likely cause. Irrigate and check the line.",
            "المجموع ضعيف مقابل نطاقه وتاريخه، وماء الأوراق دون المعتاد. نقص المياه هو السبب "
            "المرجّح. ارْوِ القطعة وافحص الخط.",
            "canopy_cause_water",
        ),
        rule(
            ["vigour_low", "block_declining", "nutrient_low"],
            "alert",
            "fertilize",
            "The canopy is weak against its band and its own history, and red-edge is below "
            "normal. A nitrogen shortage is the likely cause. Feed the block.",
            "المجموع ضعيف مقابل نطاقه وتاريخه، والحافة الحمراء دون المعتاد. نقص النيتروجين هو "
            "السبب المرجّح. سمّد القطعة.",
            "canopy_cause_nitrogen",
        ),
        rule(
            ["vigour_low", "block_declining", "dry", "nutrient_low"],
            "alert",
            "scout",
            "The canopy is weak and both leaf water and red-edge are below normal. Water and "
            "nutrition cannot be separated from the imagery. Scout the block before spending "
            "on either.",
            "المجموع ضعيف وكل من ماء الأوراق والحافة الحمراء دون المعتاد. لا يمكن فصل المياه "
            "عن التغذية من الصور. افحص القطعة قبل الإنفاق على أي منهما.",
            "canopy_cause_combined",
        ),
        rule(
            ["vigour_low", "block_declining"],
            "issue",
            "scout",
            "The canopy is below its band and below its own history, and no single cause "
            "stands out in the imagery. Scout the block.",
            "المجموع دون نطاقه ودون تاريخه، ولا يبرز سبب واحد في الصور. افحص القطعة.",
            "canopy_no_cause",
        ),
        rule(
            ["vigour_low"],
            "issue",
            "scout",
            "The canopy is below the band for this tree size, but it is not below the block's "
            "own history. This can be a young or thin block rather than a new problem.",
            "المجموع دون النطاق لهذا الحجم، لكنه ليس دون تاريخ القطعة. قد تكون قطعة صغيرة أو "
            "خفيفة، لا مشكلة جديدة.",
            "canopy_band_only",
        ),
        rule(
            ["vigour_low", "cover_open"],
            "alert",
            "scout",
            "The canopy is below its band and more bare ground is showing than expected for "
            "this tree size. On a young block this reads as lost saplings. Count the gaps and "
            "plan replanting.",
            "المجموع دون نطاقه والأرض العارية أكثر من المتوقع لهذا الحجم. في قطعة صغيرة يُقرأ "
            "هذا كشتلات مفقودة. عُدّ الفجوات وخطّط لإعادة الزراعة.",
            "canopy_weak_and_open",
        ),
        rule(
            ["block_declining"],
            "issue",
            "scout",
            "The block is falling against its own history for this day of year while still "
            "inside its band. Watch it, and scout if it falls again.",
            "القطعة تهبط مقابل تاريخها لهذا اليوم من السنة وهي ما زالت داخل نطاقها. راقبها، "
            "وافحصها إن هبطت مرة أخرى.",
            "canopy_declining_only",
        ),
        rule(
            ["block_declining", "cover_open"],
            "issue",
            "scout",
            "The block is falling against its own history and more bare ground is showing. "
            "Check whether trees have been lost.",
            "القطعة تهبط مقابل تاريخها وظهرت أرض عارية أكثر. تحقّق مما إذا كانت أشجار قد فُقدت.",
            "canopy_declining_open",
        ),
        rule(
            ["cover_open"],
            "issue",
            "scout",
            "More bare ground is showing than the guide expects for this tree size, while the "
            "canopy itself reads normally. Check the stand rather than the trees.",
            "الأرض العارية أكثر مما يتوقعه الدليل لهذا الحجم، بينما المجموع نفسه طبيعي. تحقّق "
            "من عدد الأشجار لا من صحتها.",
            "canopy_open_only",
        ),
        rule(
            ["size_missing"],
            "na",
            "no_action",
            "No tree size is recorded for this block, so no vigour band could be checked. Set "
            "the Tree size attribute on the crop assignment.",
            "لا يوجد حجم شجرة مسجّل لهذه القطعة، فلم يمكن فحص نطاق الحيوية. اضبط خاصية حجم "
            "الشجرة على تخصيص المحصول.",
            "canopy_size_missing",
        ),
    ]

    return {
        "code": "mango_canopy_and_stand",
        "name_en": "Mango — canopy vigour and stand",
        "name_ar": "المانجو — حيوية المجموع وعدد الأشجار",
        "description_en": (
            "Is the canopy weaker than it should be, and is the cause the trees or the number "
            "of trees? Picks the vigour index the guide recommends for the recorded tree size "
            "— MSAVI for small, SAVI for medium, NDVI for large — and compares it against the "
            "size band and against the block's own day-of-year history. When both say weak, "
            "it reads bare ground, leaf water and red-edge to name the cause on one card."
        ),
        "description_ar": (
            "هل المجموع أضعف مما ينبغي، وهل السبب الأشجار أم عددها؟ يختار مؤشر الحيوية الذي "
            "يوصي به الدليل لحجم الشجرة المسجّل — MSAVI للصغيرة وSAVI للمتوسطة وNDVI للكبيرة "
            "— ويقارنه بنطاق الحجم وبتاريخ القطعة لهذا اليوم من السنة. وحين يتفق الاثنان على "
            "الضعف، يقرأ الأرض العارية وماء الأوراق والحافة الحمراء ليسمّي السبب في بطاقة واحدة."
        ),
        "scope": "cell",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_size_small",
        "registers": [
            "vigour_low",
            "block_declining",
            "cover_open",
            "dry",
            "nutrient_low",
            "size_missing",
        ],
        "parameters": parameters,
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# 3. mango_nutrition
# ---------------------------------------------------------------------


def build_nutrition() -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    nodes.update(
        size_gate(
            {"small": "n_bands_small", "medium": "n_bands_medium", "large": "n_bands_large"},
            "n_reg_size_missing",
        )
    )
    for size, ar_size in (("small", "الصغيرة"), ("medium", "المتوسطة"), ("large", "الكبيرة")):
        nodes[f"n_bands_{size}"] = setter(
            f"Load the {size}-tree feeding bands",
            f"حمّل نطاقات التغذية للأشجار {ar_size}",
            {
                "size_class": size,
                "ndre_floor": param(f"{size}_ndre_floor"),
                "gndvi_floor": param(f"{size}_gndvi_floor"),
            },
            "n_ndre_check",
        )
    nodes["n_reg_size_missing"] = register(
        "No tree size is recorded, so no band could be checked",
        "لا يوجد حجم شجرة مسجّل، فلا يمكن فحص أي نطاق",
        "size_missing",
        "info",
        "n_stop",
    )

    nodes["n_ndre_check"] = cond(
        "Is red-edge below the nitrogen band for this tree size?",
        "هل الحافة الحمراء دون نطاق النيتروجين لهذا الحجم؟",
        op("le", idx("ndre"), var("ndre_floor")),
        "n_reg_nutrient",
        "n_gndvi_check",
    )
    nodes["n_reg_nutrient"] = register(
        "Leaf nitrogen is below the band",
        "نيتروجين الأوراق دون النطاق",
        "nutrient_low",
        "warning",
        "n_gndvi_check",
    )
    nodes["n_gndvi_check"] = cond(
        "Is leaf chlorophyll below the band for this tree size?",
        "هل كلوروفيل الأوراق دون النطاق لهذا الحجم؟",
        op("le", idx("gndvi"), var("gndvi_floor")),
        "n_reg_chlorophyll",
        "n_post_harvest_gate",
    )
    nodes["n_reg_chlorophyll"] = register(
        "Leaf chlorophyll is below the band and the leaves may be old or starved",
        "كلوروفيل الأوراق دون النطاق وقد تكون الأوراق مسنّة أو جائعة",
        "chlorophyll_low",
        "warning",
        "n_post_harvest_gate",
    )
    nodes["n_post_harvest_gate"] = cond(
        "Is the block in the post-harvest flush?",
        "هل القطعة في دفعة النمو بعد الحصاد؟",
        op_in(STAGE, ["post_harvest_flush"]),
        "n_reg_post_harvest_feed",
        "n_stop",
    )
    nodes["n_reg_post_harvest_feed"] = register(
        "The post-harvest recovery feed is due",
        "تغذية التعافي بعد الحصاد مستحقّة",
        "post_harvest_feed_due",
        "info",
        "n_stop",
    )
    nodes["n_stop"] = dict(STOP)

    parameters = {
        "small_ndre_floor": number(0.08, -1.0, 1.0),
        "medium_ndre_floor": number(0.18, -1.0, 1.0),
        "large_ndre_floor": number(0.38, -1.0, 1.0),
        "small_gndvi_floor": number(0.12, -1.0, 1.0),
        "medium_gndvi_floor": number(0.3, -1.0, 1.0),
        "large_gndvi_floor": number(0.59, -1.0, 1.0),
    }

    combos = [
        rule(
            ["nutrient_low", "chlorophyll_low"],
            "alert",
            "fertilize",
            "Red-edge and green both read below the band for this tree size. Two independent "
            "readings agree on a feeding shortage. Feed the block.",
            "الحافة الحمراء والأخضر كلاهما دون النطاق لهذا الحجم. قراءتان مستقلتان تتفقان على "
            "نقص تغذية. سمّد القطعة.",
            "feed_both_low",
        ),
        rule(
            ["nutrient_low"],
            "issue",
            "fertilize",
            "Red-edge is below the nitrogen band for this tree size. This shows before any "
            "yellowing is visible to the eye. Feed the block.",
            "الحافة الحمراء دون نطاق النيتروجين لهذا الحجم. يظهر هذا قبل أن يُرى أي اصفرار "
            "بالعين. سمّد القطعة.",
            "feed_nitrogen",
        ),
        rule(
            ["chlorophyll_low"],
            "issue",
            "scout",
            "Leaf chlorophyll is below the band while red-edge is not. This separates tired "
            "old leaves from a shortage. Look at leaf age before feeding.",
            "كلوروفيل الأوراق دون النطاق بينما الحافة الحمراء ليست كذلك. هذا يفصل الأوراق "
            "المسنّة عن النقص. انظر إلى عمر الأوراق قبل التسميد.",
            "feed_chlorophyll",
        ),
        rule(
            ["post_harvest_feed_due"],
            "issue",
            "fertilize",
            "The block is in the post-harvest flush and the balanced recovery feed is due. "
            "This is the feed that rebuilds reserves for next season's flowering.",
            "القطعة في دفعة النمو بعد الحصاد وتغذية التعافي المتوازنة مستحقّة. هذه هي التغذية "
            "التي تعيد بناء المخزون لتزهير الموسم القادم.",
            "feed_post_harvest",
        ),
        rule(
            ["nutrient_low", "post_harvest_feed_due"],
            "alert",
            "fertilize",
            "The block is rebuilding reserves after harvest and red-edge is already below the "
            "band. Reserves are not rebuilding. Feed now.",
            "القطعة تعيد بناء مخزونها بعد الحصاد والحافة الحمراء دون النطاق بالفعل. المخزون لا "
            "يُبنى. سمّد الآن.",
            "feed_post_harvest_short",
        ),
        rule(
            ["chlorophyll_low", "post_harvest_feed_due"],
            "issue",
            "fertilize",
            "The block is in the post-harvest flush and leaf chlorophyll is below the band. "
            "Give the recovery feed and check leaf age.",
            "القطعة في دفعة ما بعد الحصاد وكلوروفيل الأوراق دون النطاق. أعطِ تغذية التعافي "
            "وافحص عمر الأوراق.",
            "feed_post_harvest_chlorophyll",
        ),
        rule(
            ["nutrient_low", "chlorophyll_low", "post_harvest_feed_due"],
            "alert",
            "fertilize",
            "Both feeding readings are below the band in the post-harvest flush, the one "
            "window where the tree must rebuild reserves. Feed now.",
            "قراءتا التغذية كلتاهما دون النطاق في دفعة ما بعد الحصاد، وهي النافذة الوحيدة التي "
            "يجب أن تعيد فيها الشجرة بناء مخزونها. سمّد الآن.",
            "feed_post_harvest_both",
        ),
        rule(
            ["size_missing"],
            "na",
            "no_action",
            "No tree size is recorded for this block, so no feeding band could be checked. Set "
            "the Tree size attribute on the crop assignment.",
            "لا يوجد حجم شجرة مسجّل لهذه القطعة، فلم يمكن فحص نطاق التغذية. اضبط خاصية حجم "
            "الشجرة على تخصيص المحصول.",
            "feed_size_missing",
        ),
    ]

    return {
        "code": "mango_nutrition",
        "name_en": "Mango — feeding",
        "name_ar": "المانجو — التغذية",
        "description_en": (
            "Does this cell need feeding, and with what? Reads red-edge for nitrogen "
            "sufficiency and green for leaf chlorophyll and leaf age, both against the band "
            "for the recorded tree size. Red-edge is used rather than NDVI because a dense "
            "mango canopy saturates NDVI before a shortage shows. In the post-harvest flush "
            "the card changes from a warning into the recovery feed."
        ),
        "description_ar": (
            "هل تحتاج هذه الخلية إلى تسميد، وبماذا؟ يقرأ الحافة الحمراء لكفاية النيتروجين "
            "والأخضر لكلوروفيل الأوراق وعمرها، كليهما مقابل النطاق لحجم الشجرة المسجّل. "
            "تُستخدم الحافة الحمراء بدل NDVI لأن مجموع المانجو الكثيف يُشبع NDVI قبل ظهور "
            "النقص. وفي دفعة ما بعد الحصاد تتحوّل البطاقة من تحذير إلى تغذية التعافي."
        ),
        "scope": "cell",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_size_small",
        "registers": [
            "nutrient_low",
            "chlorophyll_low",
            "post_harvest_feed_due",
            "size_missing",
        ],
        "parameters": parameters,
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# 4. mango_pest_disease
# ---------------------------------------------------------------------


def build_pest() -> dict[str, Any]:
    nodes: dict[str, Any] = {
        "n_anth_stage": cond(
            "Is the block carrying tissue anthracnose can reach?",
            "هل تحمل القطعة أنسجة يصلها الأنثراكنوز؟",
            op_in(STAGE, ["flowering", "fruit_set", "fruit_development", "maturation"]),
            "n_anth_switch",
            "n_mildew_stage",
        ),
        "n_anth_switch": {
            "label_en": "How strongly do conditions favour anthracnose infection?",
            "label_ar": "إلى أي حد ترجّح الظروف إصابة الأنثراكنوز؟",
            "switch": {
                "on": risk("anthracnose"),
                "cases": [
                    {"ge": param("high_score"), "go": "n_reg_pest_high"},
                    {"ge": param("warn_score"), "go": "n_reg_pest_med"},
                ],
                "default": "n_mildew_stage",
            },
        },
        "n_reg_pest_high": register(
            "Anthracnose pressure is high",
            "ضغط الأنثراكنوز مرتفع",
            "pest_high",
            "critical",
            "n_mildew_stage",
        ),
        "n_reg_pest_med": register(
            "Anthracnose pressure is building",
            "ضغط الأنثراكنوز يتصاعد",
            "pest_med",
            "warning",
            "n_mildew_stage",
        ),
        "n_mildew_stage": cond(
            "Is the block in bloom or setting fruit?",
            "هل القطعة في التزهير أو عقد الثمار؟",
            op_in(STAGE, ["flowering", "fruit_set"]),
            "n_mildew_switch",
            "n_fly_stage",
        ),
        "n_mildew_switch": {
            "label_en": "How strongly do conditions favour powdery mildew?",
            "label_ar": "إلى أي حد ترجّح الظروف البياض الدقيقي؟",
            "switch": {
                "on": risk("powdery_mildew"),
                "cases": [
                    {"ge": param("high_score"), "go": "n_reg_mildew_high"},
                    {"ge": param("warn_score"), "go": "n_reg_mildew_med"},
                ],
                "default": "n_fly_stage",
            },
        },
        "n_reg_mildew_high": register(
            "Powdery mildew pressure is high",
            "ضغط البياض الدقيقي مرتفع",
            "mildew_high",
            "critical",
            "n_fly_stage",
        ),
        "n_reg_mildew_med": register(
            "Powdery mildew pressure is rising while the block is in bloom",
            "ضغط البياض الدقيقي يرتفع والقطعة في التزهير",
            "mildew_med",
            "warning",
            "n_fly_stage",
        ),
        "n_fly_stage": cond(
            "Is this a bearing block with ripening fruit on the tree?",
            "هل هذه قطعة مثمرة تحمل ثمارًا ناضجة؟",
            {
                "all_of": [
                    op("eq", attr("bearing_status"), "bearing"),
                    op_in(STAGE, ["maturation"]),
                ]
            },
            "n_fly_switch",
            "n_stop",
        ),
        "n_fly_switch": {
            "label_en": "How strongly do conditions favour fruit fly activity?",
            "label_ar": "إلى أي حد ترجّح الظروف نشاط ذبابة الفاكهة؟",
            "switch": {
                "on": risk("fruit_fly"),
                "cases": [
                    {"ge": param("high_score"), "go": "n_reg_fly_high"},
                    {"ge": param("warn_score"), "go": "n_reg_fly_med"},
                ],
                "default": "n_stop",
            },
        },
        "n_reg_fly_high": register(
            "Fruit fly pressure is high",
            "ضغط ذبابة الفاكهة مرتفع",
            "fly_high",
            "critical",
            "n_stop",
        ),
        "n_reg_fly_med": register(
            "Fruit fly pressure is rising on ripening fruit",
            "ضغط ذبابة الفاكهة يرتفع على ثمار ناضجة",
            "fly_med",
            "warning",
            "n_stop",
        ),
        "n_stop": dict(STOP),
    }

    parameters = {
        "warn_score": number(40, 0, 100),
        "high_score": number(70, 0, 100),
    }

    mildew_high_text = (
        "Powdery mildew pressure is high while the block is in bloom. Treat with sulfur, and "
        "time the spray away from peak pollinator hours. Mango is insect pollinated, so a "
        "spray at the wrong hour costs more fruit than the disease it prevents."
    )
    mildew_high_ar = (
        "ضغط البياض الدقيقي مرتفع والقطعة في التزهير. عالج بالكبريت، ووقّت الرش بعيدًا عن ساعات "
        "ذروة الملقّحات. المانجو يُلقّح بالحشرات، والرش في الساعة الخطأ يكلّف من الثمار أكثر مما "
        "يمنعه المرض."
    )
    anth_high_text = (
        "Anthracnose pressure is high. Send someone in with instructions for anthracnose and "
        "for mango mealybug on the same visit: the mealybug has no model on this platform and "
        "is checked here rather than not at all."
    )
    anth_high_ar = (
        "ضغط الأنثراكنوز مرتفع. أرسل من يفحص القطعة بتعليمات للأنثراكنوز ولبقّ المانجو الدقيقي "
        "في الزيارة نفسها: البقّ الدقيقي بلا نموذج على هذه المنصة، ويُفحص هنا بدل ألّا يُفحص."
    )

    combos = [
        rule(["mildew_high"], "alert", "spray", mildew_high_text, mildew_high_ar, "mildew_high"),
        rule(
            ["mildew_med"],
            "issue",
            "scout",
            "Powdery mildew pressure is rising while the block is in bloom. Check the "
            "inflorescences and be ready to treat.",
            "ضغط البياض الدقيقي يرتفع والقطعة في التزهير. افحص النورات وكن مستعدًا للعلاج.",
            "mildew_med",
        ),
        rule(["pest_high"], "alert", "spray", anth_high_text, anth_high_ar, "anth_high"),
        rule(
            ["pest_med"],
            "issue",
            "scout",
            "Anthracnose pressure is building. Check the fruit and the young leaves, and look "
            "for mealybug on the same visit.",
            "ضغط الأنثراكنوز يتصاعد. افحص الثمار والأوراق الحديثة، وابحث عن البقّ الدقيقي في "
            "الزيارة نفسها.",
            "anth_med",
        ),
        rule(
            ["fly_high"],
            "alert",
            "scout",
            "Fruit fly pressure is high on ripening fruit. Check the traps and make a control "
            "decision now, while the fruit is still on the tree.",
            "ضغط ذبابة الفاكهة مرتفع على ثمار ناضجة. افحص المصايد واتخذ قرار المكافحة الآن، "
            "والثمار ما زالت على الشجرة.",
            "fly_high",
        ),
        rule(
            ["fly_med"],
            "issue",
            "scout",
            "Fruit fly pressure is rising on ripening fruit. Check the traps.",
            "ضغط ذبابة الفاكهة يرتفع على ثمار ناضجة. افحص المصايد.",
            "fly_med",
        ),
        rule(
            ["pest_high", "mildew_high"],
            "alert",
            "spray",
            "Anthracnose and powdery mildew pressure are both high in the same bloom window. "
            "One visit covers both. Time the sulfur away from peak pollinator hours.",
            "ضغط الأنثراكنوز والبياض الدقيقي مرتفع في نافذة التزهير نفسها. زيارة واحدة تغطي "
            "الاثنين. وقّت الكبريت بعيدًا عن ساعات ذروة الملقّحات.",
            "anth_high_mildew_high",
        ),
        rule(
            ["pest_high", "mildew_med"],
            "alert",
            "spray",
            "Anthracnose pressure is high and mildew is rising in the same bloom window. Treat "
            "for anthracnose and check the inflorescences on the same visit.",
            "ضغط الأنثراكنوز مرتفع والبياض الدقيقي يتصاعد في نافذة التزهير نفسها. عالج "
            "الأنثراكنوز وافحص النورات في الزيارة نفسها.",
            "anth_high_mildew_med",
        ),
        rule(
            ["pest_med", "mildew_high"],
            "alert",
            "spray",
            "Mildew pressure is high and anthracnose is building in the same bloom window. "
            "Treat with sulfur away from peak pollinator hours and check the fruitlets.",
            "ضغط البياض الدقيقي مرتفع والأنثراكنوز يتصاعد في نافذة التزهير نفسها. عالج بالكبريت "
            "بعيدًا عن ساعات ذروة الملقّحات وافحص العُقد الصغيرة.",
            "anth_med_mildew_high",
        ),
        rule(
            ["pest_med", "mildew_med"],
            "issue",
            "scout",
            "Both anthracnose and mildew pressure are building in the bloom window. One "
            "scouting visit covers both.",
            "ضغط الأنثراكنوز والبياض الدقيقي يتصاعد في نافذة التزهير. زيارة فحص واحدة تغطي "
            "الاثنين.",
            "anth_med_mildew_med",
        ),
        rule(
            ["pest_high", "fly_high"],
            "alert",
            "spray",
            "Anthracnose and fruit fly pressure are both high on ripening fruit. One visit "
            "covers the spray decision and the trap check.",
            "ضغط الأنثراكنوز وذبابة الفاكهة مرتفع على ثمار ناضجة. زيارة واحدة تغطي قرار الرش "
            "وفحص المصايد.",
            "anth_high_fly_high",
        ),
        rule(
            ["pest_high", "fly_med"],
            "alert",
            "spray",
            "Anthracnose pressure is high and fruit fly is rising on ripening fruit. Treat, "
            "and check the traps on the same visit.",
            "ضغط الأنثراكنوز مرتفع وذبابة الفاكهة تتصاعد على ثمار ناضجة. عالج، وافحص المصايد في "
            "الزيارة نفسها.",
            "anth_high_fly_med",
        ),
        rule(
            ["pest_med", "fly_high"],
            "alert",
            "scout",
            "Fruit fly pressure is high and anthracnose is building on ripening fruit. Check "
            "the traps and the fruit on one visit.",
            "ضغط ذبابة الفاكهة مرتفع والأنثراكنوز يتصاعد على ثمار ناضجة. افحص المصايد والثمار "
            "في زيارة واحدة.",
            "anth_med_fly_high",
        ),
        rule(
            ["pest_med", "fly_med"],
            "issue",
            "scout",
            "Anthracnose and fruit fly pressure are both building on ripening fruit. One "
            "scouting visit covers both.",
            "ضغط الأنثراكنوز وذبابة الفاكهة يتصاعد على ثمار ناضجة. زيارة فحص واحدة تغطي "
            "الاثنين.",
            "anth_med_fly_med",
        ),
    ]

    return {
        "code": "mango_pest_disease",
        "name_en": "Mango — pest and disease pressure",
        "name_ar": "المانجو — ضغط الآفات والأمراض",
        "description_en": (
            "How hard is the weather pushing pests and disease on this block now? Reads the "
            "three weather-driven pressure scores the platform computes — anthracnose, powdery "
            "mildew and fruit fly — and gates each on the growth stage where it matters. The "
            "fold writes one visit instead of three cards. Block scope, because the weather "
            "score is keyed to the farm and every cell would read the same number."
        ),
        "description_ar": (
            "إلى أي حد يدفع الطقس الآفات والأمراض على هذه القطعة الآن؟ يقرأ درجات الضغط الثلاث "
            "التي تحسبها المنصة من الطقس — الأنثراكنوز والبياض الدقيقي وذبابة الفاكهة — ويقيّد "
            "كلًّا منها بمرحلة النمو التي تهمّها. يكتب الدمج زيارة واحدة بدل ثلاث بطاقات. على "
            "مستوى القطعة، لأن درجة الطقس مرتبطة بالمزرعة وكل خلية ستقرأ الرقم نفسه."
        ),
        "scope": "block",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_anth_stage",
        "registers": [
            "pest_high",
            "pest_med",
            "mildew_high",
            "mildew_med",
            "fly_high",
            "fly_med",
        ],
        "parameters": parameters,
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# 5. mango_flowering_program
# ---------------------------------------------------------------------


def build_flowering() -> dict[str, Any]:
    nodes: dict[str, Any] = {
        "n_pre_gate": cond(
            "Is the block in the pre-flowering (induction) stage?",
            "هل القطعة في مرحلة ما قبل التزهير (التصويم)؟",
            op_in(STAGE, ["pre_flowering"]),
            "n_flush_check",
            "n_fruit_set_gate",
        ),
        "n_flush_check": cond(
            "Is the canopy still growing against this block's own history?",
            "هل ما زال المجموع ينمو مقارنة بتاريخ هذه القطعة؟",
            op("ge", idx("ndvi", "baseline_deviation"), param("flush_z")),
            "n_reg_flush_active",
            "n_reg_induction_ready",
        ),
        "n_reg_flush_active": register(
            "The vegetative flush has not stopped yet",
            "لم تتوقف دفعة النمو الخضري بعد",
            "flush_active",
            "info",
            "n_wet_check",
        ),
        "n_reg_induction_ready": register(
            "The flush has stopped and the dry period can start",
            "توقفت دفعة النمو ويمكن بدء فترة التصويم",
            "induction_ready",
            "warning",
            "n_wet_check",
        ),
        "n_wet_check": cond(
            "Is the canopy well-watered while the forecast is cool?",
            "هل المجموع مُروى جيدًا والتوقع بارد؟",
            {
                "all_of": [
                    op("gt", idx("ndmi"), param("wet_ndmi")),
                    op("le", forecast("air_temp_c_min"), param("cool_induction_c")),
                ]
            },
            "n_reg_wet_and_cool",
            "n_stop",
        ),
        "n_reg_wet_and_cool": register(
            "Canopy moisture is high in the cool induction window",
            "رطوبة المجموع مرتفعة في نافذة التصويم الباردة",
            "wet_and_cool",
            "warning",
            "n_stop",
        ),
        "n_fruit_set_gate": cond(
            "Is the block setting fruit?",
            "هل القطعة في عقد الثمار؟",
            op_in(STAGE, ["fruit_set"]),
            "n_reg_early_program",
            "n_fruit_dev_gate",
        ),
        "n_reg_early_program": register(
            "The early half of the fruit program is due",
            "النصف المبكر من برنامج الثمار مستحقّ",
            "fruit_program_early_due",
            "info",
            "n_stop",
        ),
        "n_fruit_dev_gate": cond(
            "Is the block in fruit development?",
            "هل القطعة في مرحلة نمو الثمار؟",
            op_in(STAGE, ["fruit_development"]),
            "n_reg_late_program",
            "n_stop",
        ),
        "n_reg_late_program": register(
            "The late half of the fruit program is due",
            "النصف المتأخر من برنامج الثمار مستحقّ",
            "fruit_program_late_due",
            "info",
            "n_stop",
        ),
        "n_stop": dict(STOP),
    }

    parameters = {
        "flush_z": number(0.8, 0.0, 5.0),
        "wet_ndmi": number(0.3, -1.0, 1.0),
        "cool_induction_c": number(15.0, 0.0, 30.0),
    }

    combos = [
        rule(
            ["flush_active"],
            "good",
            "no_action",
            "The canopy is still growing, so the flush has not hardened off. Hold the dry "
            "period: starting it now induces a weak, uneven bloom.",
            "ما زال المجموع ينمو، فلم تنضج الدفعة بعد. أجّل فترة التصويم: بدؤها الآن يعطي "
            "تزهيرًا ضعيفًا غير منتظم.",
            "flower_hold",
        ),
        rule(
            ["induction_ready"],
            "issue",
            "no_action",
            "The flush has stopped. Start the 50 to 60 day dry period: withhold irrigation, "
            "stop nitrogen, and move to a potassium-only feed.",
            "توقفت الدفعة. ابدأ فترة التصويم من 50 إلى 60 يومًا: أوقف الريّ، وأوقف النيتروجين، "
            "وانتقل إلى تسميد بالبوتاسيوم فقط.",
            "flower_start_dry",
        ),
        rule(
            ["flush_active", "wet_and_cool"],
            "issue",
            "irrigate",
            "The canopy is still growing and it is being watered into a cool window. Reduce "
            "water now so the flush hardens off instead of pushing more growth.",
            "المجموع ما زال ينمو ويُروى في نافذة باردة. اخفض المياه الآن كي تنضج الدفعة بدل "
            "دفع نمو جديد.",
            "flower_wet_flush",
        ),
        rule(
            ["induction_ready", "wet_and_cool"],
            "alert",
            "irrigate",
            "The block is ready for induction but the canopy is still well-watered in a cool "
            "window. Withhold irrigation now, or it flushes instead of flowering.",
            "القطعة جاهزة للتصويم لكن المجموع ما زال مرويًا في نافذة باردة. أوقف الريّ الآن، "
            "وإلا دفعت نموًا خضريًا بدل التزهير.",
            "flower_withhold_now",
        ),
        rule(
            ["fruit_program_early_due"],
            "issue",
            "spray",
            "Fruit set: the first KNO3 foliar spray and fruit thinning are due, with the shift "
            "to a low-nitrogen potassium-rich feed. The day counts run from flower induction.",
            "عقد الثمار: الرشة الورقية الأولى من نترات البوتاسيوم وخفّ الثمار مستحقّان، مع "
            "الانتقال إلى تسميد منخفض النيتروجين غني بالبوتاسيوم. تُحسب الأيام من التصويم.",
            "fruit_early",
        ),
        rule(
            ["fruit_program_late_due"],
            "issue",
            "spray",
            "Fruit development: the second KNO3 foliar spray and the bulking irrigation are "
            "due. Keep nitrogen low and potassium high.",
            "نمو الثمار: الرشة الثانية من نترات البوتاسيوم وريّة التحجيم مستحقّتان. أبقِ "
            "النيتروجين منخفضًا والبوتاسيوم مرتفعًا.",
            "fruit_late",
        ),
    ]

    return {
        "code": "mango_flowering_program",
        "name_en": "Mango — flowering and fruit program",
        "name_ar": "المانجو — برنامج التزهير والإثمار",
        "description_en": (
            "What is due in the flowering and fruit-set part of the season? In pre-flowering "
            "it uses canopy greenness against the block's own history to decide whether the "
            "vegetative flush has stopped, then says hold or start the 50 to 60 day dry "
            "period. It also warns when the canopy is well-watered while the forecast is cool, "
            "which pushes a flush instead of flowers. Through fruit set and fruit development "
            "it gives the due half of the KNO3 and thinning program."
        ),
        "description_ar": (
            "ما المستحقّ في جزء التزهير وعقد الثمار من الموسم؟ في ما قبل التزهير يستخدم خضرة "
            "المجموع مقابل تاريخ القطعة ليقرّر هل توقفت دفعة النمو الخضري، ثم يقول أجّل أو ابدأ "
            "فترة التصويم من 50 إلى 60 يومًا. وينبّه كذلك حين يكون المجموع مرويًا والتوقع باردًا، "
            "فهذا يدفع نموًا خضريًا بدل الأزهار. وخلال عقد الثمار ونموها يعطي النصف المستحقّ من "
            "برنامج نترات البوتاسيوم والخفّ."
        ),
        "scope": "block",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_pre_gate",
        "registers": [
            "flush_active",
            "induction_ready",
            "wet_and_cool",
            "fruit_program_early_due",
            "fruit_program_late_due",
        ],
        "parameters": parameters,
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# 6. mango_harvest_post_harvest
# ---------------------------------------------------------------------


def build_harvest() -> dict[str, Any]:
    nodes: dict[str, Any] = {
        "n_bearing_gate": cond(
            "Is this a bearing block this season?",
            "هل هذه قطعة مثمرة هذا الموسم؟",
            op("eq", attr("bearing_status"), "bearing"),
            "n_maturity_gate",
            "n_stop",
        ),
        "n_maturity_gate": cond(
            "Is the block in its maturity window?",
            "هل القطعة في نافذة النضج؟",
            op_in(STAGE, ["maturation"]),
            "n_reg_picking",
            "n_post_harvest_gate",
        ),
        "n_reg_picking": register(
            "The block needs its repeated selective picking passes",
            "تحتاج القطعة مرورات الجني الانتقائي المتكرّرة",
            "picking_due",
            "warning",
            "n_stop",
        ),
        "n_post_harvest_gate": cond(
            "Is the block in the post-harvest flush?",
            "هل القطعة في دفعة النمو بعد الحصاد؟",
            op_in(STAGE, ["post_harvest_flush"]),
            "n_reg_post_harvest_care",
            "n_stop",
        ),
        "n_reg_post_harvest_care": register(
            "Post-harvest pruning, sanitation and recovery are due",
            "التقليم والتطهير والتعافي بعد الحصاد مستحقّة",
            "post_harvest_care_due",
            "warning",
            "n_stop",
        ),
        "n_stop": dict(STOP),
    }

    combos = [
        rule(
            ["picking_due"],
            "issue",
            "harvest_window",
            "The fruit is in its maturity window. Mango does not ripen evenly, so plan "
            "repeated selective picking passes rather than one strip pick. If the fruit is "
            "going to an export market, book the hot water treatment now: several importing "
            "countries require it.",
            "الثمار في نافذة النضج. المانجو لا ينضج بانتظام، فخطّط مرورات جني انتقائي متكرّرة "
            "بدل جني واحد شامل. وإن كانت الثمار للتصدير فاحجز المعاملة بالماء الساخن الآن: "
            "تشترطها عدة دول مستوردة.",
            "harvest_picking",
        ),
        rule(
            ["post_harvest_care_due"],
            "issue",
            "prune",
            "The block has entered the post-harvest flush. Four things are due in this window: "
            "structural pruning, orchard sanitation, a balanced recovery feed, and resuming "
            "irrigation so the flush can grow and mature before flower induction.",
            "دخلت القطعة دفعة النمو بعد الحصاد. أربعة أمور مستحقّة في هذه النافذة: التقليم "
            "الهيكلي، وتطهير البستان، وتغذية تعافٍ متوازنة، واستئناف الريّ كي تنمو الدفعة "
            "وتنضج قبل التصويم.",
            "harvest_post_care",
        ),
    ]

    return {
        "code": "mango_harvest_post_harvest",
        "name_en": "Mango — harvest and post-harvest",
        "name_ar": "المانجو — الحصاد وما بعده",
        "description_en": (
            "What is due while the fruit is on the tree, and what is due once it is off? On a "
            "bearing block in the maturity window it carries the repeated selective picking "
            "passes mango needs and the hot water treatment export markets require. Once the "
            "block enters the post-harvest flush it lists pruning, sanitation, the recovery "
            "feed and the irrigation restart. No index can see whether a block was pruned, so "
            "this tree reads no imagery. Fruit fly pressure stays in the pest tree."
        ),
        "description_ar": (
            "ما المستحقّ والثمار على الشجرة، وما المستحقّ بعد نزولها؟ في قطعة مثمرة داخل نافذة "
            "النضج يحمل مرورات الجني الانتقائي المتكرّرة التي يحتاجها المانجو والمعاملة بالماء "
            "الساخن التي تشترطها أسواق التصدير. وحين تدخل القطعة دفعة ما بعد الحصاد يذكر "
            "التقليم والتطهير وتغذية التعافي واستئناف الريّ. لا يرى أي مؤشر إن كانت القطعة قد "
            "قُلّمت، فهذه الشجرة لا تقرأ صورًا. ويبقى ضغط ذبابة الفاكهة في شجرة الآفات."
        ),
        "scope": "block",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_bearing_gate",
        "registers": ["picking_due", "post_harvest_care_due"],
        "parameters": {},
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# 7. mango_records
# ---------------------------------------------------------------------


def build_records() -> dict[str, Any]:
    nodes: dict[str, Any] = {
        "n_size_known": cond(
            "Is a tree size recorded for this block?",
            "هل يوجد حجم شجرة مسجّل لهذه القطعة؟",
            op_in(attr("tree_size_class"), ["small", "medium", "large"]),
            "n_recorded_small",
            "n_reg_size_missing",
        ),
        "n_reg_size_missing": register(
            "No tree size is recorded on the crop assignment",
            "لا يوجد حجم شجرة مسجّل على تخصيص المحصول",
            "size_missing",
            "warning",
            "n_stop",
        ),
        "n_recorded_small": cond(
            "Is the block recorded as small trees?",
            "هل القطعة مسجّلة كأشجار صغيرة؟",
            op("eq", attr("tree_size_class"), "small"),
            "n_small_reads_bigger",
            "n_recorded_large",
        ),
        "n_small_reads_bigger": cond(
            "Does the imagery read as a larger size class?",
            "هل تُقرأ الصور كفئة حجم أكبر؟",
            {
                "all_of": [
                    op("ge", idx("ndvi"), param("medium_ndvi_floor")),
                    op("lt", idx("bsi"), param("small_bsi_floor")),
                ]
            },
            "n_reg_size_mismatch",
            "n_stop",
        ),
        "n_recorded_large": cond(
            "Is the block recorded as large trees?",
            "هل القطعة مسجّلة كأشجار كبيرة؟",
            op("eq", attr("tree_size_class"), "large"),
            "n_large_reads_smaller",
            "n_medium_out_of_band",
        ),
        "n_large_reads_smaller": cond(
            "Does the imagery read as a smaller size class?",
            "هل تُقرأ الصور كفئة حجم أصغر؟",
            {
                "all_of": [
                    op("lt", idx("ndvi"), param("large_ndvi_floor")),
                    op("gt", idx("bsi"), param("large_bsi_top")),
                ]
            },
            "n_reg_size_mismatch",
            "n_stop",
        ),
        "n_medium_out_of_band": cond(
            "Does the imagery sit outside the medium band in either direction?",
            "هل تقع الصور خارج نطاق الحجم المتوسط في أي من الاتجاهين؟",
            {
                "any_of": [
                    op("gt", idx("ndvi"), param("medium_ndvi_top")),
                    op("lt", idx("ndvi"), param("small_ndvi_top")),
                ]
            },
            "n_reg_size_mismatch",
            "n_stop",
        ),
        "n_reg_size_mismatch": register(
            "The recorded tree size disagrees with the imagery",
            "حجم الشجرة المسجّل لا يتفق مع الصور",
            "size_mismatch",
            "warning",
            "n_stop",
        ),
        "n_stop": dict(STOP),
    }

    parameters = {
        "small_ndvi_top": number(0.22, -1.0, 1.0),
        "medium_ndvi_floor": number(0.25, -1.0, 1.0),
        "medium_ndvi_top": number(0.4, -1.0, 1.0),
        "large_ndvi_floor": number(0.65, -1.0, 1.0),
        "small_bsi_floor": number(0.35, -1.0, 1.0),
        "large_bsi_top": number(0.14, -1.0, 1.0),
    }

    combos = [
        rule(
            ["size_missing"],
            "na",
            "no_action",
            "No tree size is recorded for this block. Every size-aware mango rule stops "
            "without an answer until it is set, and none of them can say why. Set the Tree "
            "size attribute on the crop assignment.",
            "لا يوجد حجم شجرة مسجّل لهذه القطعة. تتوقف كل قاعدة مانجو تعتمد على الحجم بلا إجابة "
            "حتى يُضبط، ولا تستطيع أي منها أن تقول السبب. اضبط خاصية حجم الشجرة على تخصيص "
            "المحصول.",
            "record_size_missing",
        ),
        rule(
            ["size_mismatch"],
            "issue",
            "no_action",
            "The recorded tree size does not match what the imagery shows. A wrong size makes "
            "every size-aware mango rule compare against the wrong band at once, in the same "
            "direction, with no other warning. Check the record against the block.",
            "حجم الشجرة المسجّل لا يطابق ما تُظهره الصور. الحجم الخطأ يجعل كل قاعدة مانجو تعتمد "
            "على الحجم تقارن بالنطاق الخطأ دفعة واحدة وفي الاتجاه نفسه بلا أي تنبيه آخر. راجع "
            "السجل مقابل القطعة.",
            "record_size_mismatch",
        ),
    ]

    return {
        "code": "mango_records",
        "name_en": "Mango — record check",
        "name_ar": "المانجو — فحص السجلات",
        "description_en": (
            "Are the records the other six trees depend on set, and are they right? The "
            "size-aware mango rules compare a reading against a band keyed on the block's "
            "recorded tree size, and a missing size makes all of them stop with no finding and "
            "no visible reason. This tree makes that visible, and it also checks the recorded "
            "size against what NDVI and BSI actually show. Data quality, not agronomy."
        ),
        "description_ar": (
            "هل السجلات التي تعتمد عليها الأشجار الست الأخرى مضبوطة، وهل هي صحيحة؟ تقارن قواعد "
            "المانجو المعتمدة على الحجم قراءةً بنطاق مرتبط بحجم الشجرة المسجّل للقطعة، وغياب "
            "الحجم يجعلها كلها تتوقف بلا نتيجة وبلا سبب ظاهر. تُظهر هذه الشجرة ذلك، وتفحص كذلك "
            "الحجم المسجّل مقابل ما تُظهره NDVI وBSI فعلًا. جودة بيانات لا زراعة."
        ),
        "scope": "block",
        "crop_path": "mango",
        "country_codes": ["EG"],
        "root": "n_size_known",
        "registers": ["size_missing", "size_mismatch"],
        "parameters": parameters,
        "nodes": nodes,
        "combinations": combos,
    }


# ---------------------------------------------------------------------
# The finding codes these trees register
#
# 13 of the codes are already in the platform catalogue and are left alone: a
# platform row is shared, and every card that ever carried the code quotes its
# clause, so rewording one rewords old cards too. Only the codes below are new.
# ---------------------------------------------------------------------

NEW_FINDINGS = [
    {
        "code": "soil_dry",
        "name_en": "Soil moisture below the band",
        "name_ar": "رطوبة التربة دون النطاق",
        "clause_en": "soil moisture is below the band for this tree size",
        "clause_ar": "رطوبة التربة دون النطاق لهذا الحجم",
        "default_status": "issue",
    },
    {
        "code": "canopy_hot",
        "name_en": "Canopy hotter than usual",
        "name_ar": "المجموع أسخن من المعتاد",
        "clause_en": "the canopy is warmer than the air by more than usual",
        "clause_ar": "المجموع الخضري أسخن من الهواء بأكثر من المعتاد",
        "default_status": "issue",
    },
    {
        "code": "deficit_confirmed",
        "name_en": "Pre-harvest cut on plan",
        "name_ar": "خفض ما قبل الحصاد على الخطة",
        "clause_en": "soil moisture has fallen into the reduced band the pre-harvest cut "
        "is meant to produce",
        "clause_ar": "هبطت رطوبة التربة إلى النطاق المخفّض المقصود من خفض ما قبل الحصاد",
        "default_status": "good",
    },
    {
        "code": "deficit_missing",
        "name_en": "Pre-harvest cut not done",
        "name_ar": "لم يتم خفض ما قبل الحصاد",
        "clause_en": "the block is in its maturity window and the water has not been cut",
        "clause_ar": "القطعة في نافذة النضج ولم تُخفض المياه",
        "default_status": "issue",
    },
    {
        "code": "deficit_overshot",
        "name_en": "Pre-harvest cut too deep",
        "name_ar": "خفض ما قبل الحصاد أعمق من اللازم",
        "clause_en": "the pre-harvest cut has gone deeper than intended and is costing "
        "fruit size",
        "clause_ar": "تجاوز خفض ما قبل الحصاد الحدّ المقصود وصار يكلّف حجم الثمار",
        "default_status": "alert",
    },
    {
        "code": "post_harvest_feed_due",
        "name_en": "Post-harvest recovery feed due",
        "name_ar": "تغذية التعافي بعد الحصاد مستحقّة",
        "clause_en": "the block is in the post-harvest flush and the recovery feed is due",
        "clause_ar": "القطعة في دفعة ما بعد الحصاد وتغذية التعافي مستحقّة",
        "default_status": "issue",
    },
    {
        "code": "flush_active",
        "name_en": "Vegetative flush still running",
        "name_ar": "دفعة النمو الخضري ما زالت مستمرة",
        "clause_en": "the canopy is still growing and the flush has not hardened off",
        "clause_ar": "ما زال المجموع ينمو ولم تنضج الدفعة بعد",
        "default_status": "good",
    },
    {
        "code": "induction_ready",
        "name_en": "Ready for the induction dry period",
        "name_ar": "جاهزة لفترة التصويم",
        "clause_en": "the flush has stopped and the induction dry period can start",
        "clause_ar": "توقفت الدفعة ويمكن بدء فترة التصويم",
        "default_status": "issue",
    },
    {
        "code": "wet_and_cool",
        "name_en": "Wet canopy in a cool window",
        "name_ar": "مجموع مُروى في نافذة باردة",
        "clause_en": "canopy moisture is high while the forecast is cool",
        "clause_ar": "رطوبة المجموع مرتفعة والتوقع بارد",
        "default_status": "issue",
    },
    {
        "code": "fruit_program_early_due",
        "name_en": "Early fruit program due",
        "name_ar": "برنامج الثمار المبكر مستحقّ",
        "clause_en": "the first KNO3 spray and fruit thinning are due",
        "clause_ar": "الرشة الأولى من نترات البوتاسيوم وخفّ الثمار مستحقّان",
        "default_status": "issue",
    },
    {
        "code": "fruit_program_late_due",
        "name_en": "Late fruit program due",
        "name_ar": "برنامج الثمار المتأخر مستحقّ",
        "clause_en": "the second KNO3 spray and the bulking irrigation are due",
        "clause_ar": "الرشة الثانية من نترات البوتاسيوم وريّة التحجيم مستحقّتان",
        "default_status": "issue",
    },
    {
        "code": "picking_due",
        "name_en": "Selective picking passes due",
        "name_ar": "مرورات الجني الانتقائي مستحقّة",
        "clause_en": "the fruit is in its maturity window and needs repeated selective "
        "picking passes",
        "clause_ar": "الثمار في نافذة النضج وتحتاج مرورات جني انتقائي متكرّرة",
        "default_status": "issue",
    },
    {
        "code": "post_harvest_care_due",
        "name_en": "Post-harvest care due",
        "name_ar": "رعاية ما بعد الحصاد مستحقّة",
        "clause_en": "post-harvest pruning and recovery work are due",
        "clause_ar": "أعمال التقليم والتعافي بعد الحصاد مستحقّة",
        "default_status": "issue",
    },
    {
        "code": "size_mismatch",
        "name_en": "Recorded tree size disagrees with the imagery",
        "name_ar": "حجم الشجرة المسجّل لا يتفق مع الصور",
        "clause_en": "the recorded tree size does not match what the imagery shows",
        "clause_ar": "حجم الشجرة المسجّل لا يطابق ما تُظهره الصور",
        "default_status": "issue",
    },
]


BUILDERS = [
    build_water,
    build_canopy,
    build_nutrition,
    build_pest,
    build_flowering,
    build_harvest,
    build_records,
]


def write_json(path: Path, payload: Any) -> None:
    # newline="\n" on purpose: Path.write_text translates newlines on Windows,
    # which rewrites every file with CRLF and shows up as a diff carrying no
    # change.
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    total_rules = 0
    for build in BUILDERS:
        tree = build()
        # A register node that names a code the `registers` list does not
        # declare fails the publish, and so does a combination rule over a code
        # no register writes. Both are cheap to check here and expensive to
        # find in a 422.
        registered = {
            node["register"]["code"] for node in tree["nodes"].values() if "register" in node
        }
        declared = set(tree["registers"])
        assert registered == declared, f"{tree['code']}: {registered ^ declared}"
        for combo in tree["combinations"]:
            unknown = set(combo["codes"]) - declared
            assert not unknown, f"{tree['code']} rule {combo['code']}: {unknown}"
        # A variable read before any path writes it resolves to None and fails
        # closed, so the tree quietly stops finding things.
        written = {
            name for node in tree["nodes"].values() for name in (node.get("set") or {})
        }
        read = {
            ref["name"]
            for ref in _refs(tree["nodes"])
            if ref.get("source") == "vars"
        }
        assert not (read - written), f"{tree['code']}: reads unwritten {read - written}"
        params_declared = set(tree["parameters"])
        params_read = {
            ref["name"] for ref in _refs(tree["nodes"]) if ref.get("source") == "params"
        }
        assert params_read == params_declared, (
            f"{tree['code']}: parameters {params_read ^ params_declared}"
        )
        write_json(OUT / f"{tree['code']}.definition.json", tree)
        total_rules += len(tree["combinations"])
        print(
            f"{tree['code']:<28} {len(tree['nodes']):>3} nodes  "
            f"{len(tree['registers']):>2} findings  {len(tree['combinations']):>2} rules"
        )
    write_json(OUT / "findings.json", NEW_FINDINGS)
    print(f"\n{len(BUILDERS)} trees, {total_rules} combination rules, "
          f"{len(NEW_FINDINGS)} new finding codes")
    print(f"written to {OUT}")


def _refs(obj: Any) -> list[dict[str, Any]]:
    """Every value reference in the tree, flattened."""
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        if "source" in obj and isinstance(obj.get("source"), str):
            found.append(obj)
        for value in obj.values():
            found.extend(_refs(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_refs(value))
    return found


if __name__ == "__main__":
    main()
