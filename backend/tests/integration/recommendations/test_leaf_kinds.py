"""Leaf-kind tests (PR-E): alert vs recommendation.

Trees now produce two kinds of outcomes:
  * ``kind: recommendation`` (default) — historical behaviour, writes
    to ``tenant.recommendations``.
  * ``kind: alert`` — writes to ``tenant.alerts`` via the existing
    repo; the ``rule_code`` is synthesised as
    ``f"tree:{tree_code}:{leaf_node_id}"`` so the alerts partial
    UNIQUE keeps re-evaluation idempotent.

These tests focus on the engine + loader contract: compile-time
validation of leaf kind, the engine returning kind/leaf_node_id on the
outcome, and severity-vs-confidence resolution. The DB-write side
(alerts table population from a tree leaf) gets covered in the broader
alerts-pipeline regression tests once we have a real signal source
plumbed; for PR-E we keep the surface tested in isolation.
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


def _ctx(deviation: Decimal) -> ConditionContext:
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


def _yaml_with_kind(
    *, kind: str, severity: str | None = None, leaf_id: str = "fired"
) -> dict:
    outcome: dict = {
        "kind": kind,
        "action_type": "scout" if kind == "recommendation" else "inspect",
        "text_en": "fired",
    }
    if severity is not None:
        outcome["severity"] = severity
    if kind == "recommendation":
        outcome["confidence"] = 0.8
    return {
        "code": f"pre_kind_{kind}",
        "name_en": "PR-E test",
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
                "on_match": leaf_id,
                "on_miss": "noop",
            },
            leaf_id: {"outcome": outcome},
            "noop": {"outcome": {"action_type": "no_action", "text_en": "x"}},
        },
    }


def test_default_kind_is_recommendation() -> None:
    """Leaves without an explicit `kind` default to recommendation so
    pre-PR-E trees keep their previous behaviour."""
    yaml = _yaml_with_kind(kind="recommendation")
    # Strip the explicit kind to test the default
    del yaml["nodes"]["fired"]["outcome"]["kind"]
    compiled = compile_tree(yaml, source_path="t")
    result = evaluate_tree(compiled, _ctx(Decimal("-0.20")))
    assert result.outcome is not None
    assert result.outcome.kind == "recommendation"
    assert result.outcome.leaf_node_id == "fired"


def test_alert_leaf_carries_severity_and_leaf_id() -> None:
    yaml = _yaml_with_kind(kind="alert", severity="critical")
    compiled = compile_tree(yaml, source_path="t")
    result = evaluate_tree(compiled, _ctx(Decimal("-0.20")))
    assert result.outcome is not None
    assert result.outcome.kind == "alert"
    assert result.outcome.severity == "critical"
    assert result.outcome.leaf_node_id == "fired"
    # Alert outcomes carry confidence=1 by convention; the
    # `recommendations.confidence` column won't see this value (the
    # service routes alerts to a different table).
    assert result.outcome.confidence == Decimal("1")


def test_alert_leaf_without_severity_rejected_at_compile() -> None:
    yaml = _yaml_with_kind(kind="alert", severity=None)
    with pytest.raises(DecisionTreeParseError, match="requires 'severity'"):
        compile_tree(yaml, source_path="t")


def test_alert_leaf_with_bad_severity_rejected() -> None:
    yaml = _yaml_with_kind(kind="alert", severity="urgent")  # not in vocab
    with pytest.raises(DecisionTreeParseError, match="severity"):
        compile_tree(yaml, source_path="t")


def test_unknown_kind_rejected() -> None:
    yaml = _yaml_with_kind(kind="recommendation")
    yaml["nodes"]["fired"]["outcome"]["kind"] = "memo"
    with pytest.raises(DecisionTreeParseError, match="kind"):
        compile_tree(yaml, source_path="t")


def test_recommendation_keeps_confidence() -> None:
    yaml = _yaml_with_kind(kind="recommendation")
    yaml["nodes"]["fired"]["outcome"]["confidence"] = 0.7
    compiled = compile_tree(yaml, source_path="t")
    result = evaluate_tree(compiled, _ctx(Decimal("-0.20")))
    assert result.outcome is not None
    assert result.outcome.confidence == Decimal("0.7")
