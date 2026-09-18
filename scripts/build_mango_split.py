"""Cut `mango_unified` into four trees, one per area of the work.

One tree of 74 nodes is correct for the engine and hard for a person: it has
no name that says what it does, and an author changing an irrigation band
reads past 50 nodes that have nothing to do with irrigation.

So this cuts the same graph into four, along the lines the agronomy already
draws. Nothing is rewritten: every node, band and threshold below is the one
`mango-unified-tree.md` designed, moved rather than re-authored.

    mango_water_status    Water and irrigation      35 nodes
    mango_canopy_health   Canopy vigour and feed    33 nodes
    mango_pest_pressure   Pest and disease          13 nodes
    mango_record_check    Records and readings       3 nodes

**What the cut costs.** A combination rule matches the findings of one walk,
and each tree walks alone, so a rule whose codes come from two trees cannot
fire. Five of the unified tree's rules pair a canopy finding with a water or
pest one, and those five are named in `LOST_RULES` below with what the farmer
reads instead. Everything inside one area keeps its rule.

Run it after `build_mango_unified.py`, and commit what it writes:

    python scripts/build_mango_split.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TREES = ROOT / "docs" / "trees"
SOURCE = TREES / "mango_unified.definition.json"

# --- the four trees ---------------------------------------------------
#
# `nodes` names every node that moves into the tree. `rewire` repoints the
# pointers that used to leave for a part of the graph this tree no longer
# holds: in the unified tree the areas run one into the next, so each cut
# edge becomes an edge to that tree's own stop.

STOP = "n_stop"

WATER_NODES = [
    "n_deficit_window",
    "n_n_size_small",
    "n_n_size_medium",
    "n_n_size_large",
    "n_d_size_small",
    "n_d_size_medium",
    "n_d_size_large",
    "n_bands_small",
    "n_bands_medium",
    "n_bands_large",
    "n_bands_small_deficit",
    "n_bands_medium_deficit",
    "n_bands_large_deficit",
    "n_water_src",
    "n_ndmi_check",
    "n_msi_check",
    "n_set_lw_dry_ndmi",
    "n_set_lw_ok_ndmi",
    "n_set_lw_dry_msi",
    "n_set_lw_ok_msi",
    "n_smi_check",
    "n_set_soil_dry",
    "n_set_soil_ok",
    "n_cwsi_usable",
    "n_cwsi_check",
    "n_set_canopy_hot",
    "n_set_canopy_ok",
    "n_set_canopy_unreadable",
    "n_vote_three",
    "n_vote_two",
    "n_vote_one",
    "n_reg_dry_critical",
    "n_reg_dry_warning",
    "n_reg_dry_unconfirmed",
    STOP,
]

CANOPY_NODES = [
    "n_n_size_small",
    "n_n_size_medium",
    "n_n_size_large",
    "n_bands_small",
    "n_bands_medium",
    "n_bands_large",
    "n_pick_sandy",
    "n_pick_small",
    "n_pick_large",
    "n_use_savi",
    "n_use_msavi",
    "n_use_evi",
    "n_use_ndvi",
    "n_vigour_check",
    "n_vigour_sev",
    "n_reg_vigour_info",
    "n_reg_vigour_warn",
    "n_baseline",
    "n_reg_block_declining",
    "n_ndre_stage",
    "n_ndre_check",
    "n_nutrient_sev",
    "n_reg_nutrient_info",
    "n_reg_nutrient_warn",
    "n_gndvi_check",
    "n_chlorophyll_sev",
    "n_reg_chlorophyll_info",
    "n_reg_chlorophyll_warn",
    "n_bsi_check",
    "n_cover_sev",
    "n_reg_cover_info",
    "n_reg_cover_warn",
    STOP,
]

PEST_NODES = [
    "n_anth_stage",
    "n_anth_switch",
    "n_reg_pest_high",
    "n_reg_pest_med",
    "n_mildew_stage",
    "n_mildew_switch",
    "n_reg_mildew_high",
    "n_reg_mildew_med",
    "n_fly_window",
    "n_fly_switch",
    "n_reg_fly_high",
    "n_reg_fly_med",
    STOP,
]


# The band `set` nodes load all eleven bands at once, because the unified
# tree read all eleven. A tree that reads four of them should carry four:
# an irrigation author opening the water tree and finding an NDVI floor in it
# has to work out whether it matters, and the answer is always no.
WATER_BANDS = {"ndmi_floor", "msi_ceiling", "smi_floor", "cwsi_ceiling"}
CANOPY_BANDS = {
    "ndvi_floor",
    "evi_floor",
    "savi_floor",
    "msavi_floor",
    "gndvi_floor",
    "ndre_floor",
    "bsi_ceiling",
}
# Both keep these: they say which band set was loaded, and the canopy tree's
# severity split and the water tree's deficit branch read them back.
SHARED_BAND_KEYS = {"size_class", "deficit_window"}


def trim_band_set(node: dict[str, Any], keep: set[str]) -> dict[str, Any]:
    """Drop the bands this tree never reads from a band-loading `set` node."""
    if "set" not in node:
        return node
    out = dict(node)
    out["set"] = {
        key: value for key, value in node["set"].items() if key in keep or key in SHARED_BAND_KEYS
    }
    return out


SPLIT: list[dict[str, Any]] = [
    {
        "code": "mango_water_status",
        "name_en": "Mango — water and irrigation",
        "name_ar": "المانجو — الماء والري",
        "description_en": (
            "Reads leaf water, soil moisture and canopy temperature against this tree size's "
            "bands and says whether the cell is short of water. Two of the three readings must "
            "agree before it says so. Inside the pre-harvest deficit window it uses the wider "
            "bands that window expects."
        ),
        "description_ar": (
            "يقرأ ماء الورقة ورطوبة التربة وحرارة المجموع مقابل نطاقات حجم الشجرة ويقول إن كانت "
            "الخلية تعاني نقص ماء. يجب أن تتفق قراءتان من ثلاث قبل أن يقول ذلك. وداخل نافذة الريّ "
            "الناقص قبل الحصاد يستخدم النطاقات الأوسع التي تتوقعها تلك النافذة."
        ),
        "root": "n_deficit_window",
        "nodes": WATER_NODES,
        "band_keys": WATER_BANDS,
        # The size branches used to fall through to the record check when no
        # size was recorded. That question belongs to `mango_record_check`
        # now, and a tree with no size simply has no band to judge against.
        # The band nodes used to hand the walk to the index picker, which
        # belongs to the canopy tree; here the bands lead straight into the
        # water readings. The nutrient check after the vote is the canopy
        # tree's too, so the vote ends the walk.
        "rewire": {
            "n_reg_size_missing": STOP,
            "n_pick_sandy": "n_water_src",
            "n_ndre_stage": STOP,
        },
        "rules": [
            {
                "codes": ["dry"],
                "action_type": "irrigate",
                "status": "alert",
                "text_en": (
                    "Two of the three water readings say this cell is dry. Irrigate. Check the "
                    "line and the emitters on the way: a cell that is dry while its neighbours "
                    "are not is usually a blockage rather than a schedule."
                ),
                "text_ar": (
                    "قراءتان من ثلاث قراءات للماء تقولان إن هذه الخلية جافة. اروِ القطعة. وافحص "
                    "الخط والنقّاطات أثناء ذلك: الخلية الجافة بين خلايا غير جافة يكون سببها عادةً "
                    "انسداد لا برنامج ريّ."
                ),
            },
            {
                "codes": ["dry_unconfirmed"],
                "action_type": "scout",
                "status": "issue",
                "text_en": (
                    "One water reading says dry and the other two do not. That is not enough to "
                    "act on. Look at the cell on the next visit and read it again before "
                    "changing the irrigation."
                ),
                "text_ar": (
                    "قراءة ماء واحدة تقول جفاف والقراءتان الأخريان لا. هذا لا يكفي للتصرّف. "
                    "عاين الخلية في الزيارة القادمة واقرأها مرة أخرى قبل تغيير الريّ."
                ),
            },
        ],
    },
    {
        "code": "mango_canopy_health",
        "name_en": "Mango — canopy vigour and feed",
        "name_ar": "المانجو — حيوية المجموع والتغذية",
        "description_en": (
            "Picks the vegetation index that suits the soil and the tree size, checks it against "
            "this size's band and against the block's own seasonal baseline, then checks "
            "red-edge for nitrogen, green for chlorophyll and the bare-ground share for a canopy "
            "that is opening up."
        ),
        "description_ar": (
            "يختار مؤشر الغطاء النباتي المناسب للتربة ولحجم الشجرة ويقارنه بنطاق هذا الحجم "
            "وبخط الأساس الموسمي للقطعة، ثم يفحص الحافة الحمراء للنيتروجين والأخضر للكلوروفيل "
            "ونسبة التربة العارية لانكشاف المجموع."
        ),
        "root": "n_n_size_small",
        "nodes": CANOPY_NODES,
        "band_keys": CANOPY_BANDS,
        "rewire": {"n_reg_size_missing": STOP, "n_water_src": "n_ndre_stage", "n_anth_stage": STOP},
        # Every rule from the unified tree whose codes this tree registers.
        "rules_from_source": [
            ["vigour_low"],
            ["vigour_low", "cover_open"],
            ["vigour_low", "nutrient_low"],
            ["vigour_low", "block_declining"],
            ["chlorophyll_low", "nutrient_low"],
        ],
    },
    {
        "code": "mango_pest_pressure",
        "name_en": "Mango — pest and disease pressure",
        "name_ar": "المانجو — ضغط الآفات والأمراض",
        "description_en": (
            "Reads the live anthracnose, powdery mildew and fruit fly risk scores, each only in "
            "the growth stage where it can do damage, and says how hard the weather is pushing "
            "them. It does not look at the canopy at all: pressure is worth knowing before the "
            "trees show it."
        ),
        "description_ar": (
            "يقرأ درجات خطر الأنثراكنوز والبياض الدقيقي وذبابة الفاكهة الحيّة، كلًّا في الطور الذي "
            "يمكن أن تضر فيه فقط، ويقول إلى أي حد يدفعها الطقس. ولا ينظر إلى المجموع الخضري "
            "إطلاقاً: معرفة الضغط تفيد قبل أن تُظهره الأشجار."
        ),
        "root": "n_anth_stage",
        "nodes": PEST_NODES,
        "rewire": {},
        "rules_from_source": [["pest_high", "mildew_high"]],
    },
    {
        "code": "mango_record_check",
        "name_en": "Mango — records and readings",
        "name_ar": "المانجو — السجلات والقراءات",
        "description_en": (
            "One question: is the tree size recorded for this block? Every index band in the "
            "other three trees is keyed by tree size, so a block without it is judged by nothing "
            "and says nothing. This tree is why that silence is visible."
        ),
        "description_ar": (
            "سؤال واحد: هل حجم الشجرة مسجّل لهذه القطعة؟ كل نطاقات المؤشرات في الأشجار الثلاث "
            "الأخرى مبنية على حجم الشجرة، فالقطعة بلا حجم لا يحكم عليها شيء ولا تقول شيئاً. "
            "هذه الشجرة هي ما يجعل ذلك الصمت مرئياً."
        ),
        "root": "n_size_recorded",
        # Written here rather than lifted: in the unified tree this question is
        # the tail of six size branches, and on its own it is one condition.
        "own_nodes": {
            "n_size_recorded": {
                "label_en": "Is the tree size class recorded for this block?",
                "label_ar": "هل فئة حجم الشجرة مسجّلة لهذه القطعة؟",
                "condition": {
                    "tree": {
                        "op": "in",
                        "left": {
                            "source": "crop_attribute",
                            "code": "tree_size_class",
                            "key": "value",
                        },
                        "values": ["small", "medium", "large"],
                    }
                },
                "on_match": STOP,
                "on_miss": "n_reg_size_missing",
            },
            "n_reg_size_missing": {
                "label_en": "Tree size is not recorded",
                "label_ar": "حجم الشجرة غير مسجّل",
                "register": {"code": "size_missing", "severity": "info"},
                "next": STOP,
            },
            STOP: {"label_en": "End and fold", "label_ar": "النهاية والطيّ", "stop": True},
        },
        "rules": [
            {
                "codes": ["size_missing"],
                "action_type": "other",
                "status": "na",
                "text_en": (
                    "Tree size is not recorded for this block, so no index band could be checked. "
                    "Record it once and the water, canopy and feed checks all start answering."
                ),
                "text_ar": (
                    "حجم الشجرة غير مسجّل لهذه القطعة فلا يوجد نطاق مؤشر يمكن فحصه. سجّله مرة "
                    "واحدة وتبدأ فحوص الماء والمجموع والتغذية كلها في الإجابة."
                ),
            }
        ],
    },
]

# --- what the cut costs -----------------------------------------------
#
# A rule matches the finding set of one walk. These five pair findings that
# now belong to two trees, so no walk can hold both.
LOST_RULES = {
    "vigour_low+dry": "two cards: the water tree says irrigate, the canopy tree says vigour is down",
    "vigour_low+dry+nutrient_low": "two cards, and the order of work is not stated",
    "dry+cover_open": "two cards; the blocked-line reading is not offered",
    "vigour_low+pest_high": "two cards; the canopy card does not name anthracnose as the cause",
    "vigour_low+mildew_high": "two cards; the canopy card does not name mildew as the cause",
}


def params_used(blob: Any, into: set[str]) -> None:
    """Every `{source: params, name: …}` under this object."""
    if isinstance(blob, dict):
        if blob.get("source") == "params" and isinstance(blob.get("name"), str):
            into.add(blob["name"])
        for value in blob.values():
            params_used(value, into)
    elif isinstance(blob, list):
        for item in blob:
            params_used(item, into)


def vars_read(blob: Any, into: set[str]) -> None:
    """Every `{source: vars, name: …}` under this object."""
    if isinstance(blob, dict):
        if blob.get("source") == "vars" and isinstance(blob.get("name"), str):
            into.add(blob["name"])
        for value in blob.values():
            vars_read(value, into)
    elif isinstance(blob, list):
        for item in blob:
            vars_read(item, into)


def missing_vars(nodes: dict[str, Any]) -> list[str]:
    """Variables this tree reads and no `set` node in it writes.

    The compiler does not check this and cannot: a variable is written at run
    time. A read of a name nothing wrote resolves to None and the comparison
    fails closed, so the tree simply stops finding things — the quietest way a
    cut like this one can go wrong.
    """
    written: set[str] = set()
    for node in nodes.values():
        written |= set(node.get("set", {}).keys())
    read: set[str] = set()
    vars_read(nodes, read)
    return sorted(read - written)


def registers_used(nodes: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for node in nodes.values():
        code = node.get("register", {}).get("code")
        if code and code not in out:
            out.append(code)
    return out


def rewrite_targets(node: dict[str, Any], rewire: dict[str, str], kept: set[str]) -> dict[str, Any]:
    """Repoint this node's pointers into the tree that now holds them.

    A pointer named in `rewire` takes its replacement; a pointer at a node
    this tree does not hold, and that nothing renamed, goes to the stop. That
    second rule is what keeps a cut edge from becoming a dangling target,
    which the compiler refuses.
    """
    out = dict(node)
    for key in ("on_match", "on_miss", "next"):
        target = out.get(key)
        if isinstance(target, str):
            out[key] = rewire.get(target, target if target in kept else STOP)
    if "switch" in out:
        switch = dict(out["switch"])
        cases = []
        for case in switch.get("cases", []):
            case = dict(case)
            go = case.get("go")
            if isinstance(go, str):
                case["go"] = rewire.get(go, go if go in kept else STOP)
            cases.append(case)
        switch["cases"] = cases
        default = switch.get("default")
        if isinstance(default, str):
            switch["default"] = rewire.get(default, default if default in kept else STOP)
        out["switch"] = switch
    return out


def build(source: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    if "own_nodes" in spec:
        nodes = json.loads(json.dumps(spec["own_nodes"]))
    else:
        kept = set(spec["nodes"])
        band_keys = spec.get("band_keys")
        nodes = {}
        for nid in spec["nodes"]:
            node = source["nodes"][nid]
            if band_keys is not None and nid.startswith("n_bands_"):
                node = trim_band_set(node, band_keys)
            nodes[nid] = rewrite_targets(node, spec["rewire"], kept)

    names = set()
    params_used(nodes, names)
    parameters = {k: v for k, v in source["parameters"].items() if k in names}

    rules = list(spec.get("rules", []))
    for codes in spec.get("rules_from_source", []):
        match = next(
            rule for rule in source["combinations"] if sorted(rule["codes"]) == sorted(codes)
        )
        rules.append(match)

    return {
        "code": spec["code"],
        "name_en": spec["name_en"],
        "name_ar": spec["name_ar"],
        "description_en": spec["description_en"],
        "description_ar": spec["description_ar"],
        "scope": source["scope"],
        "crop_path": source["crop_path"],
        "country_codes": source["country_codes"],
        "registers": registers_used(nodes),
        "parameters": parameters,
        "combinations": rules,
        "root": spec["root"],
        "nodes": nodes,
    }


def main() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.modules.recommendations.folding_compiler import check_folding_tree

    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    catalogue = set(
        row["code"]
        for row in json.loads((TREES / "mango_unified.findings.json").read_text(encoding="utf-8"))
    )

    covered: set[str] = set()
    failed = False
    for spec in SPLIT:
        tree = build(source, spec)
        errors = check_folding_tree(tree, known_codes=catalogue)
        for error in errors:
            failed = True
            print(f"{tree['code']}: {error.rule} {error.node_ids}: {error.message_en}")
        orphans = missing_vars(tree["nodes"])
        if orphans:
            failed = True
            print(f"{tree['code']}: reads variables nothing in it writes: {orphans}")
        covered |= set(tree["registers"])
        out = TREES / f"{tree['code']}.definition.json"
        out.write_text(json.dumps(tree, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"{tree['code']:22s} {len(tree['nodes']):3d} nodes  "
            f"{len(tree['registers']):2d} findings  "
            f"{len(tree['combinations']):2d} rules  "
            f"{len(tree['parameters']):2d} parameters"
        )

    missing = set(source["registers"]) - covered
    if missing:
        failed = True
        print(f"findings the split drops entirely: {sorted(missing)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
