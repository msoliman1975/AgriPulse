"""Pure-function tests for the recommendations decision-tree engine.

No DB needed — these exercise the walker against synthetic compiled
trees. Tests for the loader (YAML → compiled JSON, hash-based
idempotency) live in ``test_loader.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.recommendations.engine import (
    evaluate_tree,
)
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import IndicesEntry

pytestmark = [pytest.mark.integration]


_NDVI_TREE: dict[str, object] = {
    "code": "scout_for_stress_v1",
    "name_en": "Scout for stress",
    "root": "root",
    "nodes": {
        "root": {
            "label_en": "NDVI below baseline?",
            "condition": {
                "tree": {
                    "op": "lt",
                    "left": {
                        "source": "indices",
                        "index_code": "ndvi",
                        "key": "baseline_deviation",
                    },
                    "right": -0.5,
                }
            },
            "on_match": "severity_check",
            "on_miss": "leaf_no_action",
        },
        "severity_check": {
            "condition": {
                "tree": {
                    "op": "lt",
                    "left": {
                        "source": "indices",
                        "index_code": "ndvi",
                        "key": "baseline_deviation",
                    },
                    "right": -1.5,
                }
            },
            "on_match": "leaf_critical",
            "on_miss": "leaf_warning",
        },
        "leaf_critical": {
            "outcome": {
                "action_type": "scout",
                "severity": "critical",
                "confidence": 0.85,
                "valid_for_hours": 72,
                "parameters": {"priority": "high"},
                "text_en": "Scout within 24h",
                "text_ar": "افحص خلال 24 ساعة",
            }
        },
        "leaf_warning": {
            "outcome": {
                "action_type": "scout",
                "severity": "warning",
                "confidence": 0.65,
                "parameters": {"priority": "medium"},
                "text_en": "Scout within 72h",
            }
        },
        "leaf_no_action": {
            "outcome": {
                "action_type": "no_action",
                "severity": "info",
                "confidence": 0.9,
                "text_en": "No action",
            }
        },
    },
}


def _ctx_with_deviation(value: Decimal | None) -> ConditionContext:
    indices = (
        {
            "ndvi": IndicesEntry(
                time=datetime.now(UTC), mean=Decimal("0.5"), baseline_deviation=value
            )
        }
        if value is not None
        else {}
    )
    return ConditionContext(
        block_id="b1",
        crop_category="vegetables",
        indices=indices,
    )


def test_severe_drop_walks_to_critical_leaf() -> None:
    result = evaluate_tree(_NDVI_TREE, _ctx_with_deviation(Decimal("-2.0")))
    assert result.outcome is not None
    assert result.outcome.action_type == "scout"
    assert result.outcome.severity == "critical"
    assert result.outcome.confidence == Decimal("0.85")
    assert result.outcome.valid_for_hours == 72
    assert [s.node_id for s in result.path] == ["root", "severity_check", "leaf_critical"]


def test_moderate_drop_walks_to_warning_leaf() -> None:
    result = evaluate_tree(_NDVI_TREE, _ctx_with_deviation(Decimal("-0.8")))
    assert result.outcome is not None
    assert result.outcome.severity == "warning"
    assert [s.node_id for s in result.path] == ["root", "severity_check", "leaf_warning"]


def test_healthy_block_walks_to_no_action_leaf() -> None:
    result = evaluate_tree(_NDVI_TREE, _ctx_with_deviation(Decimal("0.3")))
    assert result.outcome is not None
    assert result.outcome.action_type == "no_action"
    assert [s.node_id for s in result.path] == ["root", "leaf_no_action"]


def test_missing_signal_branches_to_on_miss() -> None:
    """Missing data short-circuits the comparison to False — the engine
    follows on_miss, mirroring the shared evaluator's contract."""
    result = evaluate_tree(_NDVI_TREE, _ctx_with_deviation(None))
    assert result.outcome is not None
    assert result.outcome.action_type == "no_action"


def test_dangling_pointer_returns_error_not_crash() -> None:
    bad: dict[str, object] = {
        "code": "bad_v1",
        "name_en": "bad",
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
                        "right": 0,
                    }
                },
                "on_match": "missing",
                "on_miss": "leaf",
            },
            "leaf": {"outcome": {"action_type": "no_action", "severity": "info", "text_en": "x"}},
        },
    }
    result = evaluate_tree(bad, _ctx_with_deviation(Decimal("-1.0")))
    assert result.outcome is None
    assert result.error is not None
    assert "missing" in result.error


def test_cycle_is_bounded() -> None:
    cyclic: dict[str, object] = {
        "code": "cycle_v1",
        "name_en": "cycle",
        "root": "a",
        "nodes": {
            "a": {
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {
                            "source": "indices",
                            "index_code": "ndvi",
                            "key": "baseline_deviation",
                        },
                        "right": 100,
                    }
                },
                "on_match": "b",
                "on_miss": "leaf",
            },
            "b": {
                "condition": {
                    "tree": {
                        "op": "lt",
                        "left": {
                            "source": "indices",
                            "index_code": "ndvi",
                            "key": "baseline_deviation",
                        },
                        "right": 100,
                    }
                },
                "on_match": "a",
                "on_miss": "leaf",
            },
            "leaf": {"outcome": {"action_type": "no_action", "severity": "info", "text_en": "x"}},
        },
    }
    result = evaluate_tree(cyclic, _ctx_with_deviation(Decimal("-1.0")))
    assert result.outcome is None
    assert result.error is not None
    assert "cycle" in result.error.lower()


def test_outcome_clamps_invalid_confidence() -> None:
    tree: dict[str, object] = {
        "code": "x",
        "name_en": "x",
        "root": "leaf",
        "nodes": {
            "leaf": {
                "outcome": {
                    "action_type": "scout",
                    "severity": "info",
                    "confidence": 1.7,
                    "text_en": "x",
                }
            }
        },
    }
    result = evaluate_tree(tree, _ctx_with_deviation(None))
    assert result.outcome is not None
    assert result.outcome.confidence == Decimal("1")


def test_path_records_match_state_per_node() -> None:
    result = evaluate_tree(_NDVI_TREE, _ctx_with_deviation(Decimal("-2.0")))
    matches = [(s.node_id, s.matched) for s in result.path]
    assert matches == [
        ("root", True),
        ("severity_check", True),
        ("leaf_critical", None),
    ]
