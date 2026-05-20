"""Tests for the `parameters:` block + $params resolution (PR-B).

Pure-function: covers loader validation and the recommendations engine's
parameter substitution. The DB-level override layering lands in PR-C
(``tree_parameter_overrides`` table); for PR-B we test that:

* A declared parameter's default value flows into both condition
  comparison slots (``right`` / ``low`` / ``high`` / ``in.values``) and
  outcome.parameters.
* ``evaluate_tree(..., param_overrides=...)`` lets a caller override
  declared defaults at evaluation time.
* The loader rejects malformed parameter declarations and refs to
  undeclared parameter names so trees never ship referencing a typo.
* Trees without a ``parameters:`` block behave exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.recommendations.engine import evaluate_tree
from app.modules.recommendations.errors import DecisionTreeParseError
from app.modules.recommendations.loader import compile_tree
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import IndicesEntry

pytestmark = [pytest.mark.integration]


def _ctx_with_ndvi(deviation: Decimal) -> ConditionContext:
    return ConditionContext(
        block_id="b-test",
        indices={
            "ndvi": IndicesEntry(
                time=datetime.now(UTC),
                mean=Decimal("0.5"),
                baseline_deviation=deviation,
            )
        },
    )


_PARAMETRIZED_YAML = {
    "code": "param_demo",
    "name_en": "Param Demo",
    "parameters": {
        "ndvi_drop_threshold": {
            "type": "number",
            "default": -0.15,
            "description": "Trigger threshold",
        },
        "alert_severity": {
            "type": "enum",
            "values": ["info", "warning", "critical"],
            "default": "warning",
        },
        "within_hours": {
            "type": "integer",
            "default": 24,
        },
    },
    "root": "root",
    "nodes": {
        "root": {
            "condition": {
                "tree": {
                    "op": "lt",
                    "left": {
                        "source": "indices",
                        "index_code": "ndvi",
                        "key": "baseline_deviation",
                    },
                    "right": {"source": "params", "name": "ndvi_drop_threshold"},
                }
            },
            "on_match": "leaf_scout",
            "on_miss": "leaf_noop",
        },
        "leaf_scout": {
            "outcome": {
                "action_type": "scout",
                "text_en": "Scout for stress",
                "severity": "warning",
                "parameters": {
                    "within_hours": {"source": "params", "name": "within_hours"},
                    "severity": {"source": "params", "name": "alert_severity"},
                },
            }
        },
        "leaf_noop": {"outcome": {"action_type": "no_action", "text_en": "ok"}},
    },
}


def test_parameters_block_compiles_and_preserves_defaults() -> None:
    compiled = compile_tree(_PARAMETRIZED_YAML, source_path="t")
    assert compiled["parameters"]["ndvi_drop_threshold"]["default"] == -0.15
    assert compiled["parameters"]["alert_severity"]["values"] == [
        "info",
        "warning",
        "critical",
    ]
    assert compiled["parameters"]["within_hours"]["type"] == "integer"


def test_param_resolves_in_condition_right_via_default() -> None:
    """NDVI deviation of -0.2 is below the default threshold (-0.15), so
    the tree branches to the scout leaf."""
    compiled = compile_tree(_PARAMETRIZED_YAML, source_path="t")
    result = evaluate_tree(compiled, _ctx_with_ndvi(Decimal("-0.20")))
    assert result.outcome is not None
    assert result.outcome.action_type == "scout"


def test_param_override_at_eval_time_changes_branch() -> None:
    """Overriding the threshold to -0.25 makes deviation=-0.20 NOT trigger
    — branch flips to the no-action leaf."""
    compiled = compile_tree(_PARAMETRIZED_YAML, source_path="t")
    result = evaluate_tree(
        compiled,
        _ctx_with_ndvi(Decimal("-0.20")),
        param_overrides={"ndvi_drop_threshold": -0.25},
    )
    # leaf_noop returns action_type='no_action'; engine still returns an
    # outcome dict (service layer drops it), so check the value.
    assert result.outcome is not None
    assert result.outcome.action_type == "no_action"


def test_param_substitution_flows_into_outcome_parameters() -> None:
    compiled = compile_tree(_PARAMETRIZED_YAML, source_path="t")
    result = evaluate_tree(compiled, _ctx_with_ndvi(Decimal("-0.20")))
    assert result.outcome is not None
    assert result.outcome.parameters == {
        "within_hours": 24,
        "severity": "warning",
    }


def test_param_override_flows_into_outcome_parameters() -> None:
    compiled = compile_tree(_PARAMETRIZED_YAML, source_path="t")
    result = evaluate_tree(
        compiled,
        _ctx_with_ndvi(Decimal("-0.20")),
        param_overrides={"within_hours": 6, "alert_severity": "critical"},
    )
    assert result.outcome is not None
    assert result.outcome.parameters == {
        "within_hours": 6,
        "severity": "critical",
    }


def test_tree_without_parameters_block_still_works() -> None:
    """Regression: pre-PR-B trees have no ``parameters:`` block; they
    must compile and evaluate exactly as they did before."""
    yaml = {
        "code": "no_params",
        "name_en": "No Params",
        "root": "root",
        "nodes": {
            "root": {
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {
                            "source": "indices",
                            "index_code": "ndvi",
                            "key": "baseline_deviation",
                        },
                        "right": -0.15,
                    }
                },
                "on_match": "leaf",
                "on_miss": "noop",
            },
            "leaf": {"outcome": {"action_type": "scout", "text_en": "x"}},
            "noop": {"outcome": {"action_type": "no_action", "text_en": "ok"}},
        },
    }
    compiled = compile_tree(yaml, source_path="t")
    assert compiled["parameters"] == {}
    result = evaluate_tree(compiled, _ctx_with_ndvi(Decimal("-0.20")))
    assert result.outcome is not None
    assert result.outcome.action_type == "scout"


def test_undeclared_param_ref_rejected_at_compile() -> None:
    yaml = {
        "code": "bad",
        "name_en": "Bad",
        "parameters": {
            "declared_one": {"type": "number", "default": 1.0},
        },
        "root": "root",
        "nodes": {
            "root": {
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {
                            "source": "indices",
                            "index_code": "ndvi",
                            "key": "baseline_deviation",
                        },
                        "right": {"source": "params", "name": "typoed_name"},
                    }
                },
                "on_match": "leaf",
                "on_miss": "leaf",
            },
            "leaf": {"outcome": {"action_type": "no_action", "text_en": "x"}},
        },
    }
    with pytest.raises(DecisionTreeParseError, match="typoed_name"):
        compile_tree(yaml, source_path="t")


def test_param_missing_default_rejected() -> None:
    yaml = {
        "code": "bad_default",
        "name_en": "Bad",
        "parameters": {"no_default": {"type": "number"}},
        "root": "leaf",
        "nodes": {"leaf": {"outcome": {"action_type": "no_action", "text_en": "x"}}},
    }
    with pytest.raises(DecisionTreeParseError, match="missing 'default'"):
        compile_tree(yaml, source_path="t")


def test_enum_param_default_must_be_in_values() -> None:
    yaml = {
        "code": "bad_enum",
        "name_en": "Bad Enum",
        "parameters": {
            "phase": {
                "type": "enum",
                "values": ["a", "b"],
                "default": "c",  # not in values
            }
        },
        "root": "leaf",
        "nodes": {"leaf": {"outcome": {"action_type": "no_action", "text_en": "x"}}},
    }
    with pytest.raises(DecisionTreeParseError, match="default.*not in values"):
        compile_tree(yaml, source_path="t")


def test_unknown_param_type_rejected() -> None:
    yaml = {
        "code": "bad_type",
        "name_en": "Bad",
        "parameters": {"x": {"type": "ipaddr", "default": "1.2.3.4"}},
        "root": "leaf",
        "nodes": {"leaf": {"outcome": {"action_type": "no_action", "text_en": "x"}}},
    }
    with pytest.raises(DecisionTreeParseError, match="'type' must be one of"):
        compile_tree(yaml, source_path="t")


def test_param_override_for_undeclared_name_silently_dropped() -> None:
    """An override for a parameter that doesn't exist in the tree is
    silently dropped, not applied — defends against stale tenant
    overrides referencing a parameter the platform-shipped tree removed
    in a later version."""
    compiled = compile_tree(_PARAMETRIZED_YAML, source_path="t")
    result = evaluate_tree(
        compiled,
        _ctx_with_ndvi(Decimal("-0.20")),
        param_overrides={"phantom_param": 999, "within_hours": 12},
    )
    assert result.outcome is not None
    # within_hours override applied; phantom_param ignored entirely
    # (would have raised KeyError if engine tried to substitute it).
    assert result.outcome.parameters["within_hours"] == 12
    assert "phantom_param" not in result.outcome.parameters
