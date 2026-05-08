"""Pure-function tests for the shared condition-tree evaluator."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.shared.conditions import ConditionContext, evaluate
from app.shared.conditions.context import IndicesEntry
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import (
    BlockValueRef,
    IndicesValueRef,
    parse_value_ref,
)


def _ctx(
    ndvi_dev: Decimal | None = None,
    ndvi_mean: Decimal | None = None,
    crop_category: str | None = None,
) -> ConditionContext:
    indices: dict[str, IndicesEntry] = {}
    if ndvi_dev is not None or ndvi_mean is not None:
        indices["ndvi"] = IndicesEntry(
            time=datetime.now(UTC),
            mean=ndvi_mean,
            baseline_deviation=ndvi_dev,
        )
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        crop_category=crop_category,
        indices=indices,
    )


# ---- value-ref parsing ----------------------------------------------------


def test_parse_indices_value_ref_defaults_to_baseline_deviation() -> None:
    ref = parse_value_ref({"source": "indices", "index_code": "ndvi"})
    assert isinstance(ref, IndicesValueRef)
    assert ref.index_code == "ndvi"
    assert ref.key == "baseline_deviation"


def test_parse_indices_value_ref_explicit_mean_key() -> None:
    ref = parse_value_ref({"source": "indices", "index_code": "ndvi", "key": "mean"})
    assert isinstance(ref, IndicesValueRef)
    assert ref.key == "mean"


def test_parse_indices_value_ref_unknown_key_raises() -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref({"source": "indices", "index_code": "ndvi", "key": "median"})


def test_parse_block_value_ref_crop_category() -> None:
    ref = parse_value_ref({"source": "block", "field": "crop_category"})
    assert isinstance(ref, BlockValueRef)
    assert ref.field == "crop_category"


def test_parse_value_ref_unknown_source_raises() -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref({"source": "weather", "field": "temp_c"})


def test_parse_value_ref_non_dict_raises() -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref("not-a-dict")


# ---- single-comparison ops ------------------------------------------------


def test_lt_fires_when_deviation_below_threshold() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "indices", "index_code": "ndvi"},
        "right": -1.5,
    }
    matched, snap = evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0")))
    assert matched is True
    assert snap["values"]["indices.ndvi.baseline_deviation"] == "-2.0"


def test_lt_does_not_fire_when_above_threshold() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "indices", "index_code": "ndvi"},
        "right": -1.5,
    }
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0")))
    assert matched is False


def test_le_ge_eq_ne() -> None:
    base = {"left": {"source": "indices", "index_code": "ndvi"}, "right": -1.5}
    ctx = _ctx(ndvi_dev=Decimal("-1.5"))
    assert evaluate({**base, "op": "le"}, ctx)[0] is True
    assert evaluate({**base, "op": "ge"}, ctx)[0] is True
    assert evaluate({**base, "op": "eq"}, ctx)[0] is True
    assert evaluate({**base, "op": "ne"}, ctx)[0] is False


def test_between_inclusive() -> None:
    tree = {
        "op": "between",
        "left": {"source": "indices", "index_code": "ndvi"},
        "low": -1.5,
        "high": -0.75,
    }
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0")))[0] is True
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.5")))[0] is True  # boundary
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-0.75")))[0] is True  # boundary
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0")))[0] is False


def test_in_op_against_block_field() -> None:
    tree = {
        "op": "in",
        "left": {"source": "block", "field": "crop_category"},
        "values": ["fruit_tree", "vegetable"],
    }
    assert evaluate(tree, _ctx(crop_category="fruit_tree"))[0] is True
    assert evaluate(tree, _ctx(crop_category="cereal"))[0] is False


def test_missing_signal_short_circuits_to_false() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "indices", "index_code": "ndvi"},
        "right": -1.5,
    }
    matched, snap = evaluate(tree, _ctx())  # no ndvi entry
    assert matched is False
    assert snap["values"]["indices.ndvi.baseline_deviation"] is None


# ---- boolean composition --------------------------------------------------


def test_all_of_requires_every_child_to_match() -> None:
    tree = {
        "all_of": [
            {"op": "lt", "left": {"source": "indices", "index_code": "ndvi"}, "right": -1.0},
            {
                "op": "eq",
                "left": {"source": "block", "field": "crop_category"},
                "right": "fruit_tree",
            },
        ]
    }
    matched, snap = evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0"), crop_category="fruit_tree"))
    assert matched is True
    # both refs recorded
    assert "indices.ndvi.baseline_deviation" in snap["values"]
    assert "block.crop_category" in snap["values"]

    # one branch fails → whole tree fails
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0"), crop_category="cereal"))
    assert matched is False


def test_any_of_requires_at_least_one_child() -> None:
    tree = {
        "any_of": [
            {"op": "lt", "left": {"source": "indices", "index_code": "ndvi"}, "right": -1.5},
            {
                "op": "eq",
                "left": {"source": "block", "field": "crop_category"},
                "right": "fruit_tree",
            },
        ]
    }
    # second branch matches alone
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0"), crop_category="fruit_tree"))
    assert matched is True
    # neither matches
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0"), crop_category="cereal"))
    assert matched is False


def test_not_inverts_child_result() -> None:
    tree = {"not": {"op": "lt", "left": {"source": "indices", "index_code": "ndvi"}, "right": -1.5}}
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0")))[0] is True
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0")))[0] is False


def test_nested_boolean_tree() -> None:
    tree = {
        "all_of": [
            {
                "any_of": [
                    {
                        "op": "lt",
                        "left": {"source": "indices", "index_code": "ndvi"},
                        "right": -1.5,
                    },
                    {
                        "op": "lt",
                        "left": {"source": "indices", "index_code": "ndvi"},
                        "right": -1.0,
                    },
                ]
            },
            {
                "not": {
                    "op": "eq",
                    "left": {"source": "block", "field": "crop_category"},
                    "right": "cereal",
                }
            },
        ]
    }
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.2"), crop_category="fruit_tree"))[0] is True
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.2"), crop_category="cereal"))[0] is False


def test_empty_all_of_is_vacuously_true() -> None:
    assert evaluate({"all_of": []}, _ctx())[0] is True


def test_empty_any_of_is_vacuously_false() -> None:
    assert evaluate({"any_of": []}, _ctx())[0] is False


# ---- malformed input is permissive ---------------------------------------


def test_unknown_node_returns_false_not_raises() -> None:
    matched, snap = evaluate({"foo": "bar"}, _ctx())
    assert matched is False
    assert snap["tree_match"] is False


def test_missing_op_field_returns_false_not_raises() -> None:
    matched, _ = evaluate({"left": {"source": "indices", "index_code": "ndvi"}}, _ctx())
    assert matched is False


def test_unknown_op_returns_false() -> None:
    tree = {
        "op": "regex_match",
        "left": {"source": "indices", "index_code": "ndvi"},
        "right": ".*",
    }
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0")))
    assert matched is False


# ---- type coercion --------------------------------------------------------


def test_decimal_vs_float_compares_correctly() -> None:
    # right side is a JSON float; left side is a Decimal — coerced through Decimal
    tree = {
        "op": "lt",
        "left": {"source": "indices", "index_code": "ndvi"},
        "right": -1.5,
    }
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-1.50000001")))
    assert matched is True


def test_string_vs_string_eq() -> None:
    tree = {
        "op": "eq",
        "left": {"source": "block", "field": "crop_category"},
        "right": "fruit_tree",
    }
    matched, _ = evaluate(tree, _ctx(crop_category="fruit_tree"))
    assert matched is True


# ---- ConditionContext.from_block_signals ---------------------------------


def test_from_block_signals_adapts_alerts_signals_shape() -> None:
    ctx = ConditionContext.from_block_signals(
        block_id="x",
        crop_category="fruit_tree",
        latest_index_aggregates={
            "ndvi": {
                "time": datetime.now(UTC),
                "mean": Decimal("0.5"),
                "baseline_deviation": Decimal("-2.0"),
            }
        },
    )
    assert ctx.crop_category == "fruit_tree"
    assert "ndvi" in ctx.indices
    assert ctx.indices["ndvi"].baseline_deviation == Decimal("-2.0")
