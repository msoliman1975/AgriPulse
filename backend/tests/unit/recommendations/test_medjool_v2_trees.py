"""The 15 Medjool v2 trees in docs/trees/medjool_v2 (decisions D3-D5, D10c, D22).

Pins what the owner approved:
* every tree compiles and targets date_palm.medjool in Egypt (D9);
* trees read only catalog signals (public 0098 and 0103), the "done" records
  through ``days_since_latest`` (D6), and palm size through ``palm_phase``
  (D3: new planting = small, juvenile and onset of fruiting = medium,
  bearing = large);
* no rule writes ``spray``; the 16 "Treat" rules write ``treat`` (D4);
* tree 01 registers ``cell_cover_open`` and ``cell_nutrient_low`` (D10c);
* the catalogue holds exactly the registered codes, with both languages;
* random inputs, including missing data, never make a tree error.
"""

from __future__ import annotations

import importlib.util
import json
import random
import re
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.modules.recommendations.folding_compiler import compile_folding_tree
from app.modules.recommendations.folding_engine import walk_tree
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import (
    GridAnomalyEntry,
    IndicesEntry,
    SignalEntry,
    WaterBalanceEntry,
    WeatherSnapshot,
)

_REPO = Path(__file__).resolve().parents[4]
_TREES = _REPO / "docs" / "trees" / "medjool_v2"
_VERSIONS = _REPO / "backend" / "migrations" / "public" / "versions"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DEFS: dict[str, dict[str, Any]] = {
    d["code"]: d
    for d in (
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(_TREES.glob("*.definition.json"))
    )
}
FINDINGS = json.loads((_TREES / "findings.json").read_text(encoding="utf-8"))
_0098 = _load("0098_medjool_scouting_signals").DEFINITIONS
_0103 = _load("0103_medjool_v2_signals").DEFINITIONS
SIGNAL_KINDS = {d[0]: d[3] for d in _0098} | {d[0]: d[3] for d in _0103}
DONE_EVENTS = {"date_rpw_inspection_done", "date_trap_serviced", "date_bunches_scouted"}
PHASES = ["new_planting", "juvenile", "onset_of_fruiting", "bearing"]
TREAT_TREES = {
    "date_palm_medjool_rpw_risk": 3,
    "date_palm_medjool_dust_mite": 4,
    "date_palm_medjool_moths": 3,
    "date_palm_medjool_sap_feeders": 2,
    "date_palm_medjool_flower_leaf_fungi": 2,
    "date_palm_medjool_crown_diseases": 2,
}


def _refs(node: Any, source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("source") == source:
            out.append(node)
        for value in node.values():
            out += _refs(value, source)
    elif isinstance(node, list):
        for value in node:
            out += _refs(value, source)
    return out


def _conditions(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "op" in node and isinstance(node.get("left"), dict):
            out.append(node)
        for value in node.values():
            out += _conditions(value)
    elif isinstance(node, list):
        for value in node:
            out += _conditions(value)
    return out


def test_fifteen_trees_targeting_medjool_in_egypt() -> None:
    assert len(DEFS) == 15
    for d in DEFS.values():
        assert d["crop_path"] == "date_palm.medjool"
        assert d["country_codes"] == ["EG"]
        assert d["name_ar"]
        assert d["description_ar"]


@pytest.mark.parametrize("code", sorted(DEFS))
def test_compiles(code: str) -> None:
    d = DEFS[code]
    compile_folding_tree(d, known_codes=set(d["registers"]))


@pytest.mark.parametrize("code", sorted(DEFS))
def test_reads_only_catalog_signals(code: str) -> None:
    for ref in _refs(DEFS[code], "signals"):
        assert ref["code"] in SIGNAL_KINDS, ref
        if ref["code"] in DONE_EVENTS:
            assert ref["key"] == "days_since_latest", ref
            assert SIGNAL_KINDS[ref["code"]] == "event"


def test_palm_size_reads_palm_phase() -> None:
    hits = []
    for code, d in DEFS.items():
        for cond in _conditions(d):
            if cond["left"].get("source") == "crop_attribute":
                assert cond["left"]["code"] == "palm_phase", (code, cond)
                assert cond["op"] == "in"
                assert set(cond["values"]) <= set(PHASES)
                hits.append((code, tuple(cond["values"])))
    assert len(hits) == 8
    assert (
        "date_palm_medjool_rpw_risk",
        ("new_planting", "juvenile", "onset_of_fruiting"),
    ) in hits
    assert ("date_palm_medjool_data_readiness", tuple(PHASES)) in hits


def test_treat_replaces_spray_on_the_sixteen_rules() -> None:
    counts: Counter[str] = Counter()
    for code, d in DEFS.items():
        for rule in d["combinations"]:
            assert rule.get("action_type") != "spray", (code, rule["code"])
            if rule.get("action_type") == "treat":
                counts[code] += 1
    assert dict(counts) == TREAT_TREES
    assert sum(counts.values()) == 16


# Platform finding codes mango already owns, with mango's wording (D10c, D31).
MANGO_SHARED = {
    "cover_open",
    "nutrient_low",
    "vigour_low",
    "chlorophyll_low",
    "size_missing",
    "size_mismatch",
}


def test_medjool_uses_its_own_codes_not_mangos() -> None:
    regs = {c for d in DEFS.values() for c in d["registers"]}
    assert not MANGO_SHARED & regs
    assert {
        "cell_cover_open",
        "cell_nutrient_low",
        "cell_vigour_low",
        "cell_chlorophyll_low",
    } <= set(DEFS["date_palm_medjool_canopy_diagnosis"]["registers"])
    assert {"palm_size_missing", "palm_size_mismatch"} <= set(
        DEFS["date_palm_medjool_data_readiness"]["registers"]
    )


def test_catalogue_matches_registers_with_both_languages() -> None:
    registered = {c for d in DEFS.values() for c in d["registers"]}
    codes = [f["code"] for f in FINDINGS]
    assert len(codes) == len(set(codes)) == 83
    assert set(codes) == registered
    for f in FINDINGS:
        assert set(f) >= {
            "code",
            "name_en",
            "name_ar",
            "clause_en",
            "clause_ar",
            "default_status",
        }
        assert "action_type" not in f
        assert "already_in_platform_catalogue" not in f
        for key in ("name_ar", "clause_ar"):
            assert f[key].strip(), (f["code"], key)
        # The findings API caps names at 80 characters.
        assert len(f["name_en"]) <= 80, f["code"]
        assert len(f["name_ar"]) <= 80, f["code"]


_CODE_WORDS = re.compile(
    r"\b(dormancy|pollination|fruit_set|kimri|khalal|rutab|tamar|small|medium|large)\b"
)


@pytest.mark.parametrize("code", sorted(DEFS))
def test_arabic_labels_carry_no_english_codes(code: str) -> None:
    """D26: Arabic text names stages and sizes in Arabic, not by their codes."""
    for node_id, node in DEFS[code]["nodes"].items():
        assert not _CODE_WORDS.search(node.get("label_ar") or ""), (node_id, node["label_ar"])
    for rule in DEFS[code]["combinations"]:
        assert not _CODE_WORDS.search(rule.get("text_ar") or ""), rule["code"]


@pytest.mark.parametrize("code", sorted(DEFS))
def test_has_a_bilingual_readiness_note(code: str) -> None:
    """D15: each tree says what it needs before it can run, in both languages."""
    d = DEFS[code]
    assert d.get("readiness_note_en"), code
    assert d.get("readiness_note_ar"), code
    assert not re.search(r"[A-Za-z]", d["readiness_note_ar"]), d["readiness_note_ar"]


def test_canopy_band_backup_is_off_for_every_palm_size() -> None:
    """D32: no measured Medjool bands, so tree 01 judges only against history."""
    nodes = DEFS["date_palm_medjool_canopy_diagnosis"]["nodes"]
    for size in ("small", "medium", "large", "none"):
        band = nodes[f"n_b_{size}"]["set"]
        assert all(band[k] == -1000 for k in band if k.endswith("_floor")), size
        assert band["bsi_ceiling"] == 1000, size
    params = DEFS["date_palm_medjool_canopy_diagnosis"]["parameters"]
    assert not [p for p in params if p.endswith(("_floor", "_ceiling"))]


@pytest.mark.parametrize(
    "code", ["date_palm_medjool_young_planting", "date_palm_medjool_data_readiness"]
)
def test_other_band_checks_are_off(code: str) -> None:
    """D32: trees 12 and 13 read no workbook band either."""
    d = DEFS[code]
    assert not [p for p in d["parameters"] if p.endswith(("_floor", "_ceiling"))]
    for node in d["nodes"].values():
        right = (node.get("condition") or {}).get("tree", {}).get("right")
        if isinstance(right, int | float) and abs(right) == 1000:
            assert "band off" in node["label_en"]


# ---------------------------------------------------------------- fuzz
_IDX = ["ndvi", "savi", "msavi", "bsi", "ndmi", "ndre", "gndvi", "cwsi", "smi", "lst"]
_STAGES = ["dormancy", "pollination", "fruit_set", "kimri", "khalal", "rutab", "tamar"]
_SOILS = [
    "sandy",
    "sandy_loam",
    "loam",
    "clay_loam",
    "clay",
    "silty_loam",
    "silty_clay",
]
_SAL = ["non_saline", "slightly_saline", "moderately_saline", "strongly_saline"]


def _d(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(str(round(x, 4)))


def _context(rng: random.Random) -> ConditionContext:
    def gap() -> bool:
        return rng.random() < 0.12

    now = datetime.now(UTC)
    idx = {}
    for i in _IDX:
        if gap():
            continue
        idx[i] = IndicesEntry(
            time=now,
            mean=None if gap() else _d(rng.uniform(-0.3, 0.9)),
            baseline_deviation=None if gap() else _d(rng.uniform(-3, 3)),
            trend_direction=(None if gap() else rng.choice(["rising", "falling", "stable"])),
            cell_z=None if gap() else _d(rng.uniform(-3, 3)),
            cell_baseline_samples=None if gap() else rng.choice([0, 1, 3, 9]),
            cell_delta=None if gap() else _d(rng.uniform(-0.2, 0.2)),
            cell_trend=None if gap() else rng.choice(["rising", "falling", "stable"]),
            cell_spatial_z=None if gap() else _d(rng.uniform(-3, 3)),
            cell_valid_pct=None if gap() else _d(rng.uniform(20, 100)),
        )
    signals: dict[str, SignalEntry] = {}
    for code, kind in SIGNAL_KINDS.items():
        if gap():
            continue
        if code in DONE_EVENTS:
            signals[code] = SignalEntry(
                time=now, value_event="done", days_since_latest=_d(rng.randint(0, 90))
            )
        elif kind == "boolean":
            signals[code] = SignalEntry(time=now, value_boolean=rng.random() < 0.4)
        elif kind == "numeric":
            signals[code] = SignalEntry(
                time=now,
                value_numeric=_d(rng.uniform(0, 30)),
                value_trend_direction=rng.choice(["rising", "falling", "stable", None]),
            )
        elif kind == "categorical":
            signals[code] = SignalEntry(
                time=now,
                value_categorical=rng.choice(
                    ["flood", "basin", "drip", "khalal", "rutab", "tamar"]
                ),
            )
    block = {
        k: rng.choice(v)
        for k, v in (
            ("growth_stage", _STAGES),
            ("soil_texture", _SOILS),
            ("salinity_class", _SAL),
        )
        if not gap()
    }
    attrs = {} if gap() else {"palm_phase": rng.choice(PHASES)}
    weather = (
        None
        if gap()
        else WeatherSnapshot(
            forecast_24h={"precipitation_mm_total": _d(rng.choice([0, 1, 8]))},
            forecast_72h={
                "precipitation_mm_total": _d(rng.choice([0, 2, 15])),
                "air_temp_c_max": _d(rng.uniform(15, 48)),
                "air_temp_c_min": _d(rng.uniform(-14, 25)),
                "precipitation_probability_pct_max": _d(rng.uniform(0, 100)),
            },
            derived_today={
                "temp_mean_c": None if gap() else _d(rng.uniform(8, 38)),
                "precip_mm_30d": _d(rng.uniform(0, 30)),
                "gdd_cumulative_base10_season": (None if gap() else _d(rng.uniform(500, 6000))),
            },
            derived_yesterday={"temp_min_c": None if gap() else _d(rng.uniform(-14, 25))},
        )
    )
    balance = (
        None
        if gap()
        else WaterBalanceEntry(
            date=date.today(),
            balance_mm=_d(rng.uniform(-12, 6)),
            irrigation_logged=rng.random() < 0.6,
        )
    )
    grid = {
        i: GridAnomalyEntry(worst_z=_d(rng.uniform(0, 5)), flagged_count=1)
        for i in ("ndvi", "ndre")
        if not gap()
    }
    return ConditionContext(
        block_id="b",
        block_attributes=block,
        crop_attributes=attrs,
        indices=idx,
        signals=signals,
        weather=weather,
        water_balance=balance,
        grid=grid,
    )


def test_random_inputs_never_error_and_reach_findings() -> None:
    compiled = {
        c: compile_folding_tree(d, known_codes=set(d["registers"])) for c, d in DEFS.items()
    }
    rng = random.Random(7)
    errors: Counter[str] = Counter()
    found: Counter[str] = Counter()
    for _ in range(400):
        ctx = _context(rng)
        for code, tree in compiled.items():
            walk = walk_tree(tree, ctx)
            if walk.error:
                errors[f"{code}: {walk.error[:80]}"] += 1
            elif walk.findings:
                found[code] += 1
    assert not errors, errors.most_common(5)
    # Every tree registers something on some input, so no branch is dead.
    assert set(found) == set(DEFS), set(DEFS) - set(found)
