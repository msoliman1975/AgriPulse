"""The shipped `mango_unified` body compiles, and says what the document says.

`docs/trees/mango_unified.definition.json` is built from
`docs/proposals/mango-unified-tree.md` by `scripts/build_mango_unified.py` and
committed, so it can be posted to the authoring API without a build step. A
committed artifact drifts from its source silently; these tests are what makes
that loud.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.recommendations.folding_compiler import (
    check_folding_tree,
    compile_folding_tree,
    is_folding_shape,
    kind_of_node,
)

TREES = Path(__file__).resolve().parents[4] / "docs" / "trees"


@pytest.fixture(scope="module")
def definition() -> dict:
    return json.loads((TREES / "mango_unified.definition.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def findings() -> list[dict]:
    return json.loads((TREES / "mango_unified.findings.json").read_text(encoding="utf-8"))


def test_compiles_with_no_errors(definition: dict, findings: list[dict]) -> None:
    codes = {row["code"] for row in findings}
    errors = check_folding_tree(definition, known_codes=codes)
    assert errors == [], [f"{e.rule} {e.node_ids}: {e.message_en}" for e in errors]


def test_is_the_folding_shape(definition: dict) -> None:
    # The sweep dispatches on this. A tree that read as the old shape would be
    # walked by the old engine, which has no idea what a register node is.
    assert is_folding_shape(definition)


def test_registers_and_catalogue_are_the_same_set(definition: dict, findings: list[dict]) -> None:
    assert set(definition["registers"]) == {row["code"] for row in findings}


def test_every_clause_is_one_fragment(findings: list[dict]) -> None:
    # The fold joins clauses with commas. A clause carrying its own comma makes
    # the composed sentence unreadable, and both migrations CHECK it, so a body
    # that broke this rule would be refused at the API instead of here.
    for row in findings:
        assert "," not in row["clause_en"], row["code"]
        assert "," not in row["clause_ar"], row["code"]
        assert "،" not in row["clause_ar"], row["code"]


def test_it_is_the_whole_tree(definition: dict) -> None:
    # The counts the proposal states. They are here so a half-applied edit to
    # the document fails rather than quietly shipping a smaller tree.
    assert len(definition["nodes"]) == 74
    assert len(definition["registers"]) == 14
    assert len(definition["combinations"]) == 11
    assert len(definition["parameters"]) == 45
    assert definition["scope"] == "cell"


def test_a_lone_vigour_drop_has_its_own_rule(definition: dict) -> None:
    """The PDF's step 7, and the reason this tree exists.

    Without this rule a cell whose only finding is `vigour_low` composes to the
    catalogue clause and reads as a measurement with no instruction — the same
    dead end the 11 single-index trees have today.
    """
    sets = {frozenset(rule["codes"]) for rule in definition["combinations"]}
    assert frozenset({"vigour_low"}) in sets


def test_the_weather_risks_are_read_in_the_same_walk(definition: dict) -> None:
    """No layer publishes a score to another tree; the tree reads it itself."""
    subjects = [
        node["switch"]["on"]
        for node in definition["nodes"].values()
        if kind_of_node(node) == "switch"
    ]
    risk_codes = {s["risk_code"] for s in subjects if s.get("source") == "weather_risk"}
    assert risk_codes == {"anthracnose", "powdery_mildew", "fruit_fly"}


def test_the_compiled_body_keeps_the_targeting(definition: dict, findings: list[dict]) -> None:
    compiled = compile_folding_tree(definition, known_codes={row["code"] for row in findings})
    assert compiled["crop_paths"] == ["mango"]
    assert compiled["country_codes"] == ["EG"]
    assert compiled["scope"] == "cell"
