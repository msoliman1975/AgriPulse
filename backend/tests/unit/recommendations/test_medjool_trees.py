"""The three Medjool trees compile and only read what the seed provides.

The trees are posted to production as beta drafts after deploy
(scripts/create_medjool_trees.py), so nothing else checks them before a
person opens them in the designer. These tests do: each definition compiles
with the app's compiler against its own finding codes, every signal it reads
is one public migration 0098 seeds, and every growth stage it asks about is
one of the nine Medjool stages from 0097. A misspelled signal code would not
error; it would read as missing and take ``on_miss`` for ever.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.modules.recommendations.folding_compiler import compile_folding_tree
from app.modules.recommendations.schemas import FINDING_CODE_PATTERN
from app.modules.recommendations.status_codes import STATUS_CODES

_REPO = Path(__file__).resolve().parents[4]
_TREES = _REPO / "docs" / "trees" / "medjool"
_VERSIONS = _REPO / "backend" / "migrations" / "public" / "versions"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_FINDINGS = json.loads((_TREES / "findings.json").read_text(encoding="utf-8"))
_DEFINITIONS = {
    p.name: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted(_TREES.glob("*.definition.json"))
}
_SIGNAL_CODES = {d[0] for d in _load("0098_medjool_scouting_signals").DEFINITIONS}
_STAGE_CODES = {s["code"] for s in _load("0097_medjool_organic_catalogue").MEDJOOL_STAGES["stages"]}


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every dict inside a definition, depth first."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk(value))
    return found


def test_three_trees_are_present() -> None:
    assert sorted(d["code"] for d in _DEFINITIONS.values()) == [
        "medjool_bunch_health",
        "medjool_pollination_record",
        "medjool_red_palm_weevil",
    ]


@pytest.mark.parametrize("name", sorted(_DEFINITIONS))
def test_definition_compiles(name: str) -> None:
    definition = _DEFINITIONS[name]
    compiled = compile_folding_tree(definition, known_codes={f["code"] for f in _FINDINGS})
    assert compiled["crop_paths"] == ["date_palm.medjool"]
    assert compiled["scope"] == "block"


@pytest.mark.parametrize("name", sorted(_DEFINITIONS))
def test_reads_only_seeded_signals_and_medjool_stages(name: str) -> None:
    for item in _walk(_DEFINITIONS[name]["nodes"]):
        if item.get("source") == "signals":
            assert item["code"] in _SIGNAL_CODES, f"{name}: {item['code']} is not seeded by 0098"
        if item.get("left") == {"source": "block", "field": "growth_stage"}:
            for stage in item.get("values", [item.get("right")]):
                assert stage in _STAGE_CODES, f"{name}: stage {stage} is not a Medjool stage"


@pytest.mark.parametrize("finding", _FINDINGS, ids=lambda f: f["code"])
def test_finding_rows_pass_their_table_checks(finding: dict[str, str]) -> None:
    assert re.fullmatch(FINDING_CODE_PATTERN, finding["code"])
    assert finding["default_status"] in STATUS_CODES
    assert "," not in finding["clause_en"]
    assert "," not in finding["clause_ar"]
    assert "،" not in finding["clause_ar"]
    for field in ("name_en", "name_ar", "clause_en", "clause_ar"):
        assert finding[field].strip()


def test_every_finding_is_registered_by_a_tree() -> None:
    registered = {code for d in _DEFINITIONS.values() for code in d["registers"]}
    assert registered == {f["code"] for f in _FINDINGS}


def test_archive_list_holds_no_beta_tree() -> None:
    snapshot = json.loads((_TREES / "old_trees_to_archive.json").read_text(encoding="utf-8"))
    codes = set(snapshot["codes"])
    assert len(codes) == 41
    mango_beta = {
        "mango_water",
        "mango_nutrition",
        "mango_canopy_and_stand",
        "mango_pest_disease",
        "mango_flowering_program",
        "mango_records",
        "mango_harvest_post_harvest",
    }
    assert not codes & mango_beta
    assert "mango_overmature_risk" not in codes
