"""Pure-function tests for the grid value-ref source (G-4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.shared.conditions import ConditionContext, GridAnomalyEntry, evaluate
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import GridValueRef, parse_value_ref


def _ctx(grid: dict[str, GridAnomalyEntry] | None = None) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        grid=grid or {},
    )


def test_parse_grid_value_ref() -> None:
    ref = parse_value_ref(
        {"source": "grid", "index_code": "ndvi", "field": "flagged_count"}
    )
    assert isinstance(ref, GridValueRef)
    assert ref.index_code == "ndvi"
    assert ref.field == "flagged_count"


def test_parse_grid_rejects_missing_index_code() -> None:
    with pytest.raises(ConditionParseError, match="index_code"):
        parse_value_ref({"source": "grid", "field": "worst_z"})


def test_parse_grid_rejects_unknown_field() -> None:
    with pytest.raises(ConditionParseError, match="field"):
        parse_value_ref({"source": "grid", "index_code": "ndvi", "field": "bogus"})


def test_predicate_matches_flagged_count() -> None:
    tree = {
        "op": "ge",
        "left": {"source": "grid", "index_code": "ndvi", "field": "flagged_count"},
        "right": 5,
    }
    matched, snapshot = evaluate(
        tree,
        _ctx({"ndvi": GridAnomalyEntry(worst_z=Decimal("3.1"), flagged_count=7)}),
    )
    assert matched is True
    assert snapshot["values"]["grid.ndvi.flagged_count"] == 7


def test_predicate_matches_worst_z() -> None:
    tree = {
        "op": "gt",
        "left": {"source": "grid", "index_code": "ndvi", "field": "worst_z"},
        "right": 2.5,
    }
    matched, _ = evaluate(
        tree, _ctx({"ndvi": GridAnomalyEntry(worst_z=Decimal("3.1"), flagged_count=2)})
    )
    assert matched is True


def test_predicate_matches_severity_string() -> None:
    tree = {
        "op": "eq",
        "left": {"source": "grid", "index_code": "ndvi", "field": "severity"},
        "right": "critical",
    }
    matched, _ = evaluate(
        tree,
        _ctx({"ndvi": GridAnomalyEntry(flagged_count=1, severity="critical")}),
    )
    assert matched is True


def test_predicate_misses_when_no_anomaly_for_index() -> None:
    # No entry for the index = no current anomaly -> fail closed, same as
    # every other source on missing data.
    tree = {
        "op": "ge",
        "left": {"source": "grid", "index_code": "ndvi", "field": "flagged_count"},
        "right": 1,
    }
    matched, _ = evaluate(tree, _ctx())
    assert matched is False


def test_predicate_misses_other_index_anomaly() -> None:
    # An anomaly on NDRE doesn't satisfy an NDVI predicate.
    tree = {
        "op": "ge",
        "left": {"source": "grid", "index_code": "ndvi", "field": "flagged_count"},
        "right": 1,
    }
    matched, _ = evaluate(
        tree, _ctx({"ndre": GridAnomalyEntry(flagged_count=9)})
    )
    assert matched is False


def test_grid_anomaly_in_compound_tree() -> None:
    # The headline use case: spatial anomaly AND a second condition.
    tree = {
        "all_of": [
            {
                "op": "ge",
                "left": {"source": "grid", "index_code": "ndvi", "field": "flagged_count"},
                "right": 3,
            },
            {
                "op": "eq",
                "left": {"source": "grid", "index_code": "ndvi", "field": "severity"},
                "right": "critical",
            },
        ]
    }
    matched, _ = evaluate(
        tree,
        _ctx({"ndvi": GridAnomalyEntry(flagged_count=8, severity="critical")}),
    )
    assert matched is True
