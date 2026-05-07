"""Pure-function tests for the alerts engine.

No DB or container needed — integration marker keeps these grouped
with the rest of the alerts suite for discovery convenience.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.alerts.engine import (
    BlockSignals,
    Rule,
    evaluate_predicate,
    evaluate_rule,
    merge_rule,
)

pytestmark = [pytest.mark.integration]


_DEFAULT_RULE: dict[str, object] = {
    "code": "ndvi_severe_drop",
    "severity": "critical",
    "applies_to_crop_categories": [],
    "conditions": {
        "type": "baseline_deviation_below",
        "index_code": "ndvi",
        "threshold": -1.5,
    },
    "actions": {
        "diagnosis_en": "diag-en",
        "diagnosis_ar": "diag-ar",
        "prescription_en": "pre-en",
        "prescription_ar": "pre-ar",
    },
}


def _signals_with_ndvi(deviation: Decimal | None) -> BlockSignals:
    return BlockSignals(
        block_id="00000000-0000-0000-0000-000000000001",
        crop_category=None,
        latest_index_aggregates=(
            {
                "ndvi": {
                    "time": datetime.now(UTC),
                    "mean": Decimal("0.55"),
                    "baseline_deviation": deviation,
                }
            }
            if deviation is not None
            else {}
        ),
    )


# ---- merge_rule -----------------------------------------------------------


def test_merge_rule_returns_default_when_override_is_none() -> None:
    rule = merge_rule(default=_DEFAULT_RULE, override=None)
    assert rule is not None
    assert rule.severity == "critical"
    assert rule.conditions == _DEFAULT_RULE["conditions"]


def test_merge_rule_returns_none_when_override_disables() -> None:
    override = {
        "rule_code": "ndvi_severe_drop",
        "is_disabled": True,
    }
    assert merge_rule(default=_DEFAULT_RULE, override=override) is None


def test_merge_rule_lets_override_replace_severity_and_conditions() -> None:
    override = {
        "rule_code": "ndvi_severe_drop",
        "is_disabled": False,
        "modified_severity": "warning",
        "modified_conditions": {
            "type": "baseline_deviation_below",
            "index_code": "ndvi",
            "threshold": -2.5,
        },
        "modified_actions": None,
    }
    rule = merge_rule(default=_DEFAULT_RULE, override=override)
    assert rule is not None
    assert rule.severity == "warning"
    assert rule.conditions["threshold"] == -2.5
    # Actions kept from default since override didn't replace them.
    assert rule.actions == _DEFAULT_RULE["actions"]


# ---- evaluate_predicate --------------------------------------------------


def test_predicate_baseline_deviation_below_fires() -> None:
    fired, snap = evaluate_predicate(
        {"type": "baseline_deviation_below", "index_code": "ndvi", "threshold": -1.5},
        _signals_with_ndvi(Decimal("-2.0")),
    )
    assert fired is True
    assert snap["index_code"] == "ndvi"
    assert snap["baseline_deviation"] == "-2.0"


def test_predicate_baseline_deviation_below_skips_when_not_fired() -> None:
    fired, _snap = evaluate_predicate(
        {"type": "baseline_deviation_below", "index_code": "ndvi", "threshold": -1.5},
        _signals_with_ndvi(Decimal("-1.0")),
    )
    assert fired is False


def test_predicate_returns_false_when_signal_missing() -> None:
    fired, snap = evaluate_predicate(
        {"type": "baseline_deviation_below", "index_code": "ndvi", "threshold": -1.5},
        _signals_with_ndvi(None),
    )
    assert fired is False
    assert snap == {}


def test_predicate_baseline_deviation_between() -> None:
    fired_in, _ = evaluate_predicate(
        {
            "type": "baseline_deviation_between",
            "index_code": "ndvi",
            "low": -1.5,
            "high": -0.75,
        },
        _signals_with_ndvi(Decimal("-1.0")),
    )
    fired_out, _ = evaluate_predicate(
        {
            "type": "baseline_deviation_between",
            "index_code": "ndvi",
            "low": -1.5,
            "high": -0.75,
        },
        _signals_with_ndvi(Decimal("-2.0")),
    )
    assert fired_in is True
    assert fired_out is False


def test_unknown_predicate_type_skipped() -> None:
    fired, snap = evaluate_predicate({"type": "alien"}, _signals_with_ndvi(Decimal("-2.0")))
    assert fired is False
    assert snap == {}


# ---- evaluate_rule -------------------------------------------------------


def test_evaluate_rule_returns_candidate_with_actions() -> None:
    rule = Rule(
        code="ndvi_severe_drop",
        severity="critical",
        conditions={
            "type": "baseline_deviation_below",
            "index_code": "ndvi",
            "threshold": -1.5,
        },
        actions={
            "diagnosis_en": "low ndvi",
            "diagnosis_ar": None,
            "prescription_en": "scout",
            "prescription_ar": None,
        },
        applies_to_crop_categories=(),
    )
    candidate = evaluate_rule(rule, _signals_with_ndvi(Decimal("-2.0")))
    assert candidate is not None
    assert candidate.rule_code == "ndvi_severe_drop"
    assert candidate.severity == "critical"
    assert candidate.diagnosis_en == "low ndvi"
    assert candidate.signal_snapshot["baseline_deviation"] == "-2.0"


def test_evaluate_rule_filters_by_crop_category() -> None:
    rule = Rule(
        code="ndvi_severe_drop",
        severity="critical",
        conditions={
            "type": "baseline_deviation_below",
            "index_code": "ndvi",
            "threshold": -1.5,
        },
        actions={},
        applies_to_crop_categories=("fruit_tree",),
    )
    signals = BlockSignals(
        block_id="x",
        crop_category="cereal",
        latest_index_aggregates={
            "ndvi": {
                "time": datetime.now(UTC),
                "mean": Decimal("0.55"),
                "baseline_deviation": Decimal("-2.0"),
            }
        },
    )
    assert evaluate_rule(rule, signals) is None
