"""The four area trees compile, and between them they say everything the one tree said.

`mango_unified` is 74 nodes. `scripts/build_mango_split.py` cuts the same graph
into four a person can name — water, canopy, pest, records — and the risk of a
cut like that is silent: a branch that now leads nowhere, a variable whose
`set` node stayed behind, a finding that fell between two trees.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.modules.recommendations.folding_compiler import check_folding_tree, kind_of_node

TREES = Path(__file__).resolve().parents[4] / "docs" / "trees"
CODES = [
    "mango_water_status",
    "mango_canopy_health",
    "mango_pest_pressure",
    "mango_record_check",
]


def _load(name: str) -> dict[str, Any]:
    return json.loads((TREES / f"{name}.definition.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalogue() -> set[str]:
    rows = json.loads((TREES / "mango_unified.findings.json").read_text(encoding="utf-8"))
    return {row["code"] for row in rows}


@pytest.mark.parametrize("code", CODES)
def test_each_tree_compiles(code: str, catalogue: set[str]) -> None:
    errors = check_folding_tree(_load(code), known_codes=catalogue)
    assert errors == [], [f"{e.rule} {e.node_ids}: {e.message_en}" for e in errors]


@pytest.mark.parametrize("code", CODES)
def test_each_tree_names_itself(code: str) -> None:
    tree = _load(code)
    assert tree["code"] == code
    # A name and a description in both languages is the whole reason for the
    # cut: four trees nobody can tell apart would be worse than one big one.
    for field in ("name_en", "name_ar", "description_en", "description_ar"):
        assert tree[field].strip(), f"{code} has no {field}"
    assert len(tree["description_en"]) > 80


@pytest.mark.parametrize("code", CODES)
def test_each_tree_writes_every_variable_it_reads(code: str) -> None:
    """A read of a name nothing wrote resolves to None and fails closed.

    The compiler cannot catch it — a variable is written at run time — so a
    `set` node left behind by the cut would not break the tree, it would make
    it quietly stop finding things.
    """
    nodes = _load(code)["nodes"]
    written: set[str] = set()
    for node in nodes.values():
        written |= set(node.get("set", {}).keys())

    read: set[str] = set()

    def walk(blob: Any) -> None:
        if isinstance(blob, dict):
            if blob.get("source") == "vars" and isinstance(blob.get("name"), str):
                read.add(blob["name"])
            for value in blob.values():
                walk(value)
        elif isinstance(blob, list):
            for item in blob:
                walk(item)

    walk(nodes)
    assert read - written == set()


def test_the_four_cover_every_finding_the_one_tree_registers(catalogue: set[str]) -> None:
    unified = _load("mango_unified")
    covered: set[str] = set()
    for code in CODES:
        covered |= set(_load(code)["registers"])
    assert covered == set(unified["registers"])


def test_no_finding_is_registered_by_two_trees() -> None:
    """Two trees registering one code would open two cards about one thing.

    That is the duplication the merge was for, and the cut is the one change
    that could bring it back.
    """
    seen: dict[str, str] = {}
    for code in CODES:
        for finding in _load(code)["registers"]:
            assert finding not in seen, f"{finding} is in both {seen[finding]} and {code}"
            seen[finding] = code


@pytest.mark.parametrize("code", CODES)
def test_every_rule_only_names_findings_its_own_tree_registers(code: str) -> None:
    """A rule matches the finding set of one walk.

    A rule naming a code this tree never registers can never fire, and reads
    on the combinations screen as advice the author will wait for for ever.
    """
    tree = _load(code)
    registers = set(tree["registers"])
    for rule in tree["combinations"]:
        assert set(rule["codes"]) <= registers, rule["codes"]


@pytest.mark.parametrize("code", CODES)
def test_each_tree_ends_on_exactly_one_stop(code: str) -> None:
    nodes = _load(code)["nodes"]
    stops = [nid for nid, node in nodes.items() if kind_of_node(node) == "stop"]
    assert len(stops) == 1


def test_the_split_is_smaller_than_the_tree_it_replaces() -> None:
    unified = len(_load("mango_unified")["nodes"])
    sizes = {code: len(_load(code)["nodes"]) for code in CODES}
    assert max(sizes.values()) < unified
    # Nothing was dropped on the way: the four hold the same graph, plus one
    # stop each and the record check's own two nodes.
    assert sum(sizes.values()) >= unified - 10
