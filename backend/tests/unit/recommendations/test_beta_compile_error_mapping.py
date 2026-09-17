"""Compiler errors become the pinned 422 body.

The contract sessions C and D build against is:

    {"errors": [{"node_id": str|null, "rule": str,
                 "message_en": str, "message_ar": str}]}

Three things it has to hold, and each one has a way of quietly not holding.

**Every error, not the first.** The compiler collects, and the mapping must
not drop any. An author fixing one message per round trip is the slow path
the designer exists to remove.

**Both languages on every entry.** A blank message on an Arabic screen reads
as "no reason given", which is worse than untranslated text.

**A whole-tree problem has a null ``node_id``.** The designer puts an error
with a node id on that node and one without at the top of the list. An error
that invented a node id would be drawn next to a node that is fine.

Pure: no database, no request. `check_folding_tree` is the only thing here
that touches the tree.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.recommendations.folding_authoring import compile_errors_to_body
from app.modules.recommendations.folding_compiler import (
    CompileError,
    FoldingCompileError,
    check_folding_tree,
)


def _three_rule_failure() -> dict[str, Any]:
    """A definition that fails exactly three separable rules."""
    return {
        "code": "broken",
        "name_en": "Broken",
        "root": "n_switch",
        "registers": [],
        "nodes": {
            # 1. a switch with no default.
            "n_switch": {
                "switch": {
                    "on": {"source": "indices", "index": "ndvi", "field": "mean"},
                    "cases": [{"ge": 0.3, "go": "n_stop"}],
                }
            },
            "n_stop": {"stop": True},
            # 2. a node nothing can reach.
            "n_orphan": {"stop": True},
        },
        # 3. a rule naming a code `registers` does not declare.
        "combinations": [{"codes": ["never_declared"], "text_en": "x"}],
    }


def test_three_broken_rules_produce_three_entries() -> None:
    errors = check_folding_tree(_three_rule_failure(), known_codes=set())
    body = compile_errors_to_body(errors)

    rules = [entry["rule"] for entry in body["errors"]]
    assert "switch-without-default" in rules
    assert "unreachable-node" in rules
    assert "combination-unknown-code" in rules
    assert len(body["errors"]) == len(errors), "the mapping dropped an error"


def test_every_entry_carries_both_languages() -> None:
    errors = check_folding_tree(_three_rule_failure(), known_codes=set())
    body = compile_errors_to_body(errors)
    assert body["errors"], "the fixture must fail at least one rule"
    for entry in body["errors"]:
        assert entry["message_en"], entry["rule"]
        assert entry["message_ar"], entry["rule"]


def test_a_whole_tree_problem_has_a_null_node_id() -> None:
    body = compile_errors_to_body(check_folding_tree({"nodes": {}}, known_codes=set()))
    assert body["errors"]
    assert all(entry["node_id"] is None for entry in body["errors"])
    assert all(entry["node_ids"] == [] for entry in body["errors"])


def test_a_node_problem_names_that_node() -> None:
    body = compile_errors_to_body(check_folding_tree(_three_rule_failure(), known_codes=set()))
    switch = next(e for e in body["errors"] if e["rule"] == "switch-without-default")
    assert switch["node_id"] == "n_switch"
    assert switch["node_ids"] == ["n_switch"]


def test_a_rule_about_several_nodes_keeps_all_of_them() -> None:
    """`node_id` is the first node, `node_ids` is every one.

    "These nodes cannot be reached" is one problem about several nodes. The
    contract names `node_id`, so that field is the first — but dropping the
    rest would make the list say less is wrong than really is, and the
    designer highlights all of them.
    """
    definition = _three_rule_failure()
    definition["nodes"]["n_orphan_two"] = {"stop": True}
    body = compile_errors_to_body(check_folding_tree(definition, known_codes=set()))
    unreachable = next(e for e in body["errors"] if e["rule"] == "unreachable-node")
    assert unreachable["node_ids"] == ["n_orphan", "n_orphan_two"]
    assert unreachable["node_id"] == "n_orphan"


def test_an_error_without_arabic_repeats_the_english() -> None:
    """A fallback that never fires today, asserted so it stays correct.

    The compiler writes Arabic for every rule it has. If one ever arrives
    without, an empty string on an Arabic screen would read as "no reason
    given", so the English is repeated instead.
    """
    body = compile_errors_to_body(
        [CompileError(rule="invented", message_en="Something is wrong.", message_ar="")]
    )
    assert body["errors"][0]["message_ar"] == "Something is wrong."


def test_the_exception_carries_the_same_errors_it_was_given() -> None:
    errors = check_folding_tree(_three_rule_failure(), known_codes=set())
    exc = FoldingCompileError(errors)
    assert compile_errors_to_body(exc.errors) == compile_errors_to_body(errors)


@pytest.mark.parametrize("declared", [["dry"], ["dry", "ndvi_low"]])
def test_an_absent_catalogue_rejects_every_declared_code(declared: list[str]) -> None:
    """The honest failure when the finding catalogue is not there yet.

    `known_codes` returns an empty set when the table does not exist, so
    every entry in `registers` is rejected and each message names its own
    code. That is the state this branch ships in.
    """
    definition = _three_rule_failure()
    definition["registers"] = declared
    definition["combinations"] = []
    body = compile_errors_to_body(check_folding_tree(definition, known_codes=set()))
    unknown = [e for e in body["errors"] if e["rule"] == "registers-unknown-code"]
    assert len(unknown) == len(declared)
    for code, entry in zip(declared, unknown, strict=True):
        assert repr(code) in entry["message_en"]
        assert repr(code) in entry["message_ar"]
