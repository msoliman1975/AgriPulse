"""Unit tests for the folding decision-tree compiler.

One test per rejection rule, each asserting the message names the node the
author has to fix, plus the valid 40-node mango tree from
``folding_compiler_fixtures``. No database, no evaluation.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.recommendations.folding_compiler import (
    CompileError,
    FoldingCompileError,
    check_folding_tree,
    compile_folding_tree,
    is_folding_shape,
    kind_of_node,
)
from app.modules.recommendations.folding_compiler_fixtures import (
    MANGO_KNOWN_CODES,
    mango_folding_tree,
)

KNOWN = MANGO_KNOWN_CODES


def _errors(spec: dict[str, Any], *, known: Any = None) -> list[CompileError]:
    return check_folding_tree(spec, known_codes=KNOWN if known is None else known)


def _by_rule(errors: list[CompileError], rule: str) -> list[CompileError]:
    return [e for e in errors if e.rule == rule]


def _minimal(**overrides: Any) -> dict[str, Any]:
    """The smallest tree that compiles: one register, then stop."""
    spec: dict[str, Any] = {
        "code": "tiny",
        "name_en": "Tiny",
        "registers": ["dry"],
        "root": "root",
        "nodes": {
            "root": {"register": {"code": "dry", "severity": "warning"}, "next": "end"},
            "end": {"stop": True},
        },
    }
    spec.update(overrides)
    return spec


# --- the baseline the rejection tests vary ---------------------------------


def test_minimal_tree_compiles() -> None:
    assert _errors(_minimal()) == []


# --- rule: mixed-shapes ----------------------------------------------------


def test_rejects_outcome_leaf_beside_a_register_node() -> None:
    spec = _minimal()
    spec["nodes"]["root"]["next"] = "leaf"
    spec["nodes"]["leaf"] = {
        "outcome": {"kind": "recommendation", "action_type": "irrigate", "text_en": "Water it."}
    }
    errors = _by_rule(_errors(spec), "mixed-shapes")
    assert len(errors) == 1
    assert "'leaf'" in errors[0].message_en
    assert "'root'" in errors[0].message_en
    assert set(errors[0].node_ids) == {"leaf", "root", "end"}
    assert errors[0].message_ar


def test_outcome_only_tree_is_not_folding_shape() -> None:
    spec = {
        "code": "old",
        "name_en": "Old",
        "root": "root",
        "nodes": {"root": {"outcome": {"kind": "no_action"}}},
    }
    assert is_folding_shape(spec) is False
    assert is_folding_shape(_minimal()) is True


# --- rule: path-without-stop -----------------------------------------------


def test_rejects_a_branch_that_ends_without_stop() -> None:
    """A node is reachable, but one of its two branches is a dead end."""
    spec = _minimal()
    spec["nodes"] = {
        "root": {
            "condition": {
                "tree": {"op": "gt", "left": {"source": "block", "field": "area_ha"}, "right": 1}
            },
            "on_match": "good_branch",
            "on_miss": "dead_branch",
        },
        "good_branch": {"register": {"code": "dry", "severity": "warning"}, "next": "end"},
        "dead_branch": {"register": {"code": "dry", "severity": "warning"}, "next": "also_dead"},
        "also_dead": {"set": {"x": 1}, "next": "nowhere"},
        "end": {"stop": True},
    }
    errors = _by_rule(_errors(spec), "path-without-stop")
    assert len(errors) == 1
    assert "'also_dead'" in errors[0].message_en
    assert errors[0].node_ids == ("also_dead",)


def test_names_every_node_that_ends_without_stop_not_just_the_first() -> None:
    spec = _minimal()
    spec["nodes"] = {
        "root": {
            "switch": {
                "on": {"source": "block", "field": "growth_stage"},
                "cases": [
                    {"eq": "flowering", "go": "dead_a"},
                    {"eq": "fruit_set", "go": "dead_b"},
                ],
                "default": "dead_c",
            }
        },
        "dead_a": {"set": {"x": 1}, "next": "gone_a"},
        "dead_b": {"set": {"y": 2}, "next": "gone_b"},
        "dead_c": {"set": {"z": 3}, "next": "gone_c"},
        "end": {"stop": True},
    }
    errors = _by_rule(_errors(spec), "path-without-stop")
    assert len(errors) == 1
    assert errors[0].node_ids == ("dead_a", "dead_b", "dead_c")
    for nid in ("dead_a", "dead_b", "dead_c"):
        assert f"'{nid}'" in errors[0].message_en


def test_a_cycle_that_never_stops_is_rejected_and_does_not_hang() -> None:
    spec = _minimal()
    spec["nodes"] = {
        "root": {"set": {"x": 1}, "next": "loop_a"},
        "loop_a": {"set": {"y": 2}, "next": "loop_b"},
        "loop_b": {"set": {"z": 3}, "next": "loop_a"},
        "end": {"stop": True},
    }
    errors = _by_rule(_errors(spec), "cycle-without-stop")
    assert len(errors) == 1
    assert errors[0].node_ids == ("loop_a", "loop_b", "root")
    assert "'loop_a'" in errors[0].message_en


def test_a_cycle_with_an_exit_to_stop_is_accepted() -> None:
    spec = _minimal()
    spec["nodes"] = {
        "root": {"set": {"x": 1}, "next": "loop"},
        "loop": {
            "condition": {
                "tree": {"op": "gt", "left": {"source": "block", "field": "area_ha"}, "right": 1}
            },
            "on_match": "loop",
            "on_miss": "end",
        },
        "end": {"stop": True},
    }
    assert _by_rule(_errors(spec), "cycle-without-stop") == []
    assert _by_rule(_errors(spec), "path-without-stop") == []


# --- rule: switch-without-default ------------------------------------------


def test_rejects_a_switch_without_a_default() -> None:
    spec = _minimal()
    spec["nodes"]["root"] = {
        "switch": {
            "on": {"source": "weather_risk", "risk_code": "anthracnose", "field": "score"},
            "cases": [{"ge": 70, "go": "end"}],
        }
    }
    errors = _by_rule(_errors(spec), "switch-without-default")
    assert len(errors) == 1
    assert errors[0].node_id == "root"
    assert "'root'" in errors[0].message_en
    assert errors[0].message_ar


# --- rule: register-not-declared -------------------------------------------


def test_rejects_a_register_whose_code_is_not_in_the_registers_list() -> None:
    spec = _minimal()
    spec["nodes"]["root"]["register"]["code"] = "frost_risk"
    errors = _by_rule(_errors(spec), "register-not-declared")
    assert len(errors) == 1
    assert errors[0].node_id == "root"
    assert "'root'" in errors[0].message_en
    assert "'frost_risk'" in errors[0].message_en


def test_rejects_a_register_with_a_severity_outside_the_three() -> None:
    spec = _minimal()
    spec["nodes"]["root"]["register"]["severity"] = "urgent"
    errors = _by_rule(_errors(spec), "register-bad-severity")
    assert len(errors) == 1
    assert errors[0].node_id == "root"


# --- rule: registers-unknown-code ------------------------------------------


def test_rejects_a_registers_entry_that_is_not_a_known_finding_code() -> None:
    spec = _minimal(registers=["dry", "not_a_finding"])
    errors = _by_rule(_errors(spec), "registers-unknown-code")
    assert len(errors) == 1
    assert "'not_a_finding'" in errors[0].message_en
    assert errors[0].node_ids == ()


# --- rule: vars-not-set-on-every-path --------------------------------------


def test_rejects_a_vars_read_written_on_only_one_branch() -> None:
    spec = _minimal()
    spec["nodes"] = {
        "root": {
            "condition": {
                "tree": {"op": "gt", "left": {"source": "block", "field": "area_ha"}, "right": 1}
            },
            "on_match": "writes_it",
            "on_miss": "skips_it",
        },
        "writes_it": {"set": {"index_used": "savi"}, "next": "reads_it"},
        "skips_it": {"set": {"other": 1}, "next": "reads_it"},
        "reads_it": {
            "condition": {
                "tree": {
                    "op": "eq",
                    "left": {"source": "vars", "name": "index_used"},
                    "right": "savi",
                }
            },
            "on_match": "end",
            "on_miss": "end",
        },
        "end": {"stop": True},
    }
    errors = _by_rule(_errors(spec), "vars-not-set-on-every-path")
    assert len(errors) == 1
    assert errors[0].node_id == "reads_it"
    assert "'reads_it'" in errors[0].message_en
    assert "'index_used'" in errors[0].message_en


def test_accepts_a_vars_read_written_on_both_branches() -> None:
    spec = _minimal()
    spec["nodes"] = {
        "root": {
            "condition": {
                "tree": {"op": "gt", "left": {"source": "block", "field": "area_ha"}, "right": 1}
            },
            "on_match": "writes_a",
            "on_miss": "writes_b",
        },
        "writes_a": {"set": {"index_used": "savi"}, "next": "reads_it"},
        "writes_b": {"set": {"index_used": "ndvi"}, "next": "reads_it"},
        "reads_it": {
            "condition": {
                "tree": {
                    "op": "eq",
                    "left": {"source": "vars", "name": "index_used"},
                    "right": "savi",
                }
            },
            "on_match": "end",
            "on_miss": "end",
        },
        "end": {"stop": True},
    }
    assert _by_rule(_errors(spec), "vars-not-set-on-every-path") == []


def test_a_vars_read_inside_a_switch_is_checked_too() -> None:
    spec = _minimal()
    spec["nodes"] = {
        "root": {
            "switch": {
                "on": {"source": "vars", "name": "never_written"},
                "cases": [{"eq": "x", "go": "end"}],
                "default": "end",
            }
        },
        "end": {"stop": True},
    }
    errors = _by_rule(_errors(spec), "vars-not-set-on-every-path")
    assert len(errors) == 1
    assert errors[0].node_id == "root"
    assert "'never_written'" in errors[0].message_en


# --- rule: combination-unknown-code ----------------------------------------


def test_rejects_a_combination_whose_codes_are_not_all_declared() -> None:
    spec = _minimal(
        combinations=[
            {"codes": ["dry", "frost_risk"], "action_type": "irrigate", "text_en": "Water it."}
        ]
    )
    errors = _by_rule(_errors(spec), "combination-unknown-code")
    assert len(errors) == 1
    assert "'frost_risk'" in errors[0].message_en


def test_rejects_a_combination_with_a_status_outside_the_four() -> None:
    spec = _minimal(
        combinations=[
            {"codes": ["dry"], "status": "very_bad", "action_type": "irrigate", "text_en": "Water."}
        ]
    )
    errors = _by_rule(_errors(spec), "combination-bad-status")
    assert len(errors) == 1


def test_rejects_two_combinations_over_the_same_finding_set() -> None:
    spec = _minimal(
        registers=["dry", "ndvi_low"],
        combinations=[
            {"codes": ["dry", "ndvi_low"], "text_en": "One."},
            {"codes": ["ndvi_low", "dry"], "text_en": "Two."},
        ],
    )
    errors = _by_rule(_errors(spec), "combination-duplicate-set")
    assert len(errors) == 1


# --- structural rules ------------------------------------------------------


def test_rejects_a_next_pointing_at_an_unknown_node() -> None:
    spec = _minimal()
    spec["nodes"]["root"]["next"] = "typo"
    errors = _by_rule(_errors(spec), "unknown-target")
    assert len(errors) == 1
    assert errors[0].node_id == "root"
    assert "'typo'" in errors[0].message_en


def test_rejects_an_unreachable_node() -> None:
    spec = _minimal()
    spec["nodes"]["orphan"] = {"register": {"code": "dry", "severity": "info"}, "next": "end"}
    errors = _by_rule(_errors(spec), "unreachable-node")
    assert len(errors) == 1
    assert errors[0].node_ids == ("orphan",)


def test_rejects_a_node_that_names_no_kind() -> None:
    spec = _minimal()
    spec["nodes"]["root"] = {"label_en": "nothing here", "next": "end"}
    errors = _by_rule(_errors(spec), "unknown-node-kind")
    assert len(errors) == 1
    assert errors[0].node_id == "root"


def test_the_parameters_block_keeps_its_current_rules() -> None:
    spec = _minimal(parameters={"threshold": {"type": "number"}})
    errors = _by_rule(_errors(spec), "invalid-block")
    assert len(errors) == 1
    assert "threshold" in errors[0].message_en


def test_an_undeclared_params_ref_is_rejected() -> None:
    spec = _minimal()
    spec["nodes"]["root"] = {
        "condition": {
            "tree": {
                "op": "lt",
                "left": {"source": "indices", "index_code": "ndvi", "key": "mean"},
                "right": {"source": "params", "name": "never_declared"},
            }
        },
        "on_match": "end",
        "on_miss": "end",
    }
    errors = _by_rule(_errors(spec), "invalid-block")
    assert len(errors) == 1
    assert "never_declared" in errors[0].message_en


# --- node kind discrimination ----------------------------------------------


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"register": {"code": "dry", "severity": "info"}}, "register"),
        ({"set": {"x": 1}}, "set"),
        ({"switch": {}}, "switch"),
        ({"stop": True}, "stop"),
        ({"outcome": {}}, "outcome"),
        ({"condition": {}}, "condition"),
        ({"label_en": "x"}, "unknown"),
    ],
)
def test_kind_of_node(node: dict[str, Any], expected: str) -> None:
    assert kind_of_node(node) == expected


# --- every error carries Arabic --------------------------------------------


def test_every_rejection_message_has_an_arabic_string() -> None:
    spec = _minimal(registers=["dry", "not_a_finding"])
    spec["nodes"]["root"]["register"]["severity"] = "urgent"
    spec["nodes"]["orphan"] = {"switch": {"on": 1, "cases": [{"ge": 1, "go": "end"}]}}
    errors = _errors(spec)
    assert len(errors) >= 4
    for error in errors:
        assert error.message_en.endswith(".")
        assert error.message_ar
        assert error.message_ar != error.message_en


# --- the valid 40-node tree ------------------------------------------------


def test_the_mango_fixture_has_40_nodes() -> None:
    assert len(mango_folding_tree()["nodes"]) == 40


def test_the_mango_fixture_compiles() -> None:
    spec = mango_folding_tree()
    assert check_folding_tree(spec, known_codes=KNOWN) == []
    compiled = compile_folding_tree(spec, known_codes=KNOWN)
    assert compiled["shape"] == "folding"
    assert compiled["code"] == "mango_folding_v1"
    assert compiled["scope"] == "cell"
    assert compiled["crop_paths"] == ["mango"]
    assert len(compiled["registers"]) == 14
    assert len(compiled["combinations"]) == 5
    # The fold matches on the sorted code set, so the compiled rule holds it
    # sorted rather than in the order the author typed.
    assert compiled["combinations"][1]["codes"] == ["dry", "ndvi_low"]


def test_the_mango_fixture_returns_a_fresh_copy_each_call() -> None:
    first = mango_folding_tree()
    first["nodes"]["n_stop"]["stop"] = False
    assert mango_folding_tree()["nodes"]["n_stop"]["stop"] is True


def test_compile_raises_with_every_error_attached() -> None:
    spec = _minimal()
    spec["nodes"]["root"]["register"]["code"] = "frost_risk"
    spec["nodes"]["root"]["register"]["severity"] = "urgent"
    with pytest.raises(FoldingCompileError) as exc:
        compile_folding_tree(spec, known_codes=KNOWN)
    rules = {e.rule for e in exc.value.errors}
    assert rules == {"register-not-declared", "register-bad-severity"}
    payload = exc.value.as_dict()
    assert payload["errors"][0]["node_ids"] == ["root"]
    assert payload["errors"][0]["message_ar"]
