"""Pure-function tests for the shared condition-tree evaluator."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.shared.conditions import ConditionContext, evaluate
from app.shared.conditions.context import IndicesEntry, WeatherIndexEntry, WeatherRiskEntry
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import (
    BlockValueRef,
    IndicesValueRef,
    WeatherIndexValueRef,
    WeatherRiskValueRef,
    parse_value_ref,
)


def _ctx(
    ndvi_dev: Decimal | None = None,
    ndvi_mean: Decimal | None = None,
    soil_texture: str | None = None,
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
        block_attributes={"soil_texture": soil_texture},
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


def test_parse_block_value_ref_rejects_the_crop_identity_fields() -> None:
    # crop_category / crop_path / crop_strain all restate the tree's targeting,
    # which already declares the crop paths it runs on. Rejecting them at parse
    # time is what stops one being reintroduced by hand-written YAML.
    for field in ("crop_category", "crop_path", "crop_strain"):
        with pytest.raises(ConditionParseError):
            parse_value_ref({"source": "block", "field": field})


# ---- growth_stage block field (KB P3) -------------------------------------


def _stage_ctx(stage: str | None) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        block_attributes={"growth_stage": stage},
    )


def test_parse_block_value_ref_growth_stage() -> None:
    ref = parse_value_ref({"source": "block", "field": "growth_stage"})
    assert isinstance(ref, BlockValueRef)
    assert ref.field == "growth_stage"


def test_parse_block_value_ref_unknown_field_raises() -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref({"source": "block", "field": "bogus"})


def test_growth_stage_eq_matches_when_set() -> None:
    tree = {
        "op": "eq",
        "left": {"source": "block", "field": "growth_stage"},
        "right": "tuber_bulking",
    }
    assert evaluate(tree, _stage_ctx("tuber_bulking"))[0] is True
    assert evaluate(tree, _stage_ctx("maturation"))[0] is False


def test_growth_stage_unset_fails_closed() -> None:
    tree = {
        "op": "eq",
        "left": {"source": "block", "field": "growth_stage"},
        "right": "tuber_bulking",
    }
    # No stage set -> None -> predicate is False (fail-closed).
    assert evaluate(tree, _stage_ctx(None))[0] is False


def test_growth_stage_in_operator() -> None:
    tree = {
        "op": "in",
        "left": {"source": "block", "field": "growth_stage"},
        "values": ["tuber_initiation", "tuber_bulking"],
    }
    assert evaluate(tree, _stage_ctx("tuber_bulking"))[0] is True
    assert evaluate(tree, _stage_ctx("emergence"))[0] is False


# ---- soil block fields (phenology spine D1) -------------------------------


def _soilsize_ctx(
    *,
    soil_texture: str | None = None,
    salinity_class: str | None = None,
) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        block_attributes={
            "soil_texture": soil_texture,
            "salinity_class": salinity_class,
        },
    )


def test_parse_block_value_ref_soil_fields() -> None:
    assert parse_value_ref({"source": "block", "field": "soil_texture"}).field == "soil_texture"
    assert parse_value_ref({"source": "block", "field": "salinity_class"}).field == "salinity_class"


def test_parse_block_value_ref_rejects_canopy_size_class() -> None:
    # Removed from BLOCK_FIELDS: nothing in the product ever set the column,
    # so a predicate against it could never be true. Rejecting it at parse
    # time is what stops an author reintroducing one.
    with pytest.raises(ConditionParseError):
        parse_value_ref({"source": "block", "field": "canopy_size_class"})


def test_soil_texture_eq_branches_sandy() -> None:
    tree = {"op": "eq", "left": {"source": "block", "field": "soil_texture"}, "right": "sandy"}
    assert evaluate(tree, _soilsize_ctx(soil_texture="sandy"))[0] is True
    assert evaluate(tree, _soilsize_ctx(soil_texture="clay"))[0] is False


def test_salinity_class_in_operator_and_fails_closed() -> None:
    tree = {
        "op": "in",
        "left": {"source": "block", "field": "salinity_class"},
        "values": ["saline", "very_saline"],
    }
    assert evaluate(tree, _soilsize_ctx(salinity_class="saline"))[0] is True
    assert evaluate(tree, _soilsize_ctx(salinity_class="non_saline"))[0] is False
    # Unset -> None -> fail-closed.
    assert evaluate(tree, _soilsize_ctx(salinity_class=None))[0] is False


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
        "left": {"source": "block", "field": "soil_texture"},
        "values": ["sandy", "sandy_loam"],
    }
    assert evaluate(tree, _ctx(soil_texture="sandy"))[0] is True
    assert evaluate(tree, _ctx(soil_texture="clay"))[0] is False


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
                "left": {"source": "block", "field": "soil_texture"},
                "right": "sandy",
            },
        ]
    }
    matched, snap = evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0"), soil_texture="sandy"))
    assert matched is True
    # both refs recorded
    assert "indices.ndvi.baseline_deviation" in snap["values"]
    assert "block.soil_texture" in snap["values"]

    # one branch fails → whole tree fails
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-2.0"), soil_texture="clay"))
    assert matched is False


def test_any_of_requires_at_least_one_child() -> None:
    tree = {
        "any_of": [
            {"op": "lt", "left": {"source": "indices", "index_code": "ndvi"}, "right": -1.5},
            {
                "op": "eq",
                "left": {"source": "block", "field": "soil_texture"},
                "right": "sandy",
            },
        ]
    }
    # second branch matches alone
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0"), soil_texture="sandy"))
    assert matched is True
    # neither matches
    matched, _ = evaluate(tree, _ctx(ndvi_dev=Decimal("-1.0"), soil_texture="clay"))
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
                    "left": {"source": "block", "field": "soil_texture"},
                    "right": "clay",
                }
            },
        ]
    }
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.2"), soil_texture="sandy"))[0] is True
    assert evaluate(tree, _ctx(ndvi_dev=Decimal("-1.2"), soil_texture="clay"))[0] is False


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
        "left": {"source": "block", "field": "soil_texture"},
        "right": "sandy",
    }
    matched, _ = evaluate(tree, _ctx(soil_texture="sandy"))
    assert matched is True


# ---- ConditionContext.from_block_signals ---------------------------------


def test_from_block_signals_adapts_alerts_signals_shape() -> None:
    ctx = ConditionContext.from_block_signals(
        block_id="x",
        block_attributes={"soil_texture": "sandy"},
        latest_index_aggregates={
            "ndvi": {
                "time": datetime.now(UTC),
                "mean": Decimal("0.5"),
                "baseline_deviation": Decimal("-2.0"),
            }
        },
    )
    assert ctx.block_attributes["soil_texture"] == "sandy"
    assert "ndvi" in ctx.indices
    assert ctx.indices["ndvi"].baseline_deviation == Decimal("-2.0")


# ---- weather_index source (PR-W7) -----------------------------------------


def _wx_ctx(
    index_code: str = "temperature",
    value: Decimal | None = None,
    deviation: Decimal | None = None,
) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        weather_indices={
            index_code: WeatherIndexEntry(
                date=date(2026, 6, 20),
                value=value,
                baseline_deviation=deviation,
            )
        },
    )


def test_parse_weather_index_ref_defaults_to_baseline_deviation() -> None:
    ref = parse_value_ref({"source": "weather_index", "index_code": "temperature"})
    assert isinstance(ref, WeatherIndexValueRef)
    assert ref.index_code == "temperature"
    assert ref.key == "baseline_deviation"


def test_parse_weather_index_ref_explicit_value_key() -> None:
    ref = parse_value_ref(
        {"source": "weather_index", "index_code": "evapotranspiration", "key": "value"}
    )
    assert isinstance(ref, WeatherIndexValueRef)
    assert ref.key == "value"


def test_parse_weather_index_ref_unknown_key_raises() -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref({"source": "weather_index", "index_code": "temperature", "key": "mean"})


def test_parse_weather_index_ref_missing_index_code_raises() -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref({"source": "weather_index", "key": "value"})


def test_weather_index_zscore_predicate_fires_and_records_snapshot() -> None:
    # Heat anomaly: temperature index sitting >2 sigma above the seasonal normal.
    tree = {
        "op": "gt",
        "left": {"source": "weather_index", "index_code": "temperature"},
        "right": 2,
    }
    matched, snap = evaluate(tree, _wx_ctx(deviation=Decimal("2.6")))
    assert matched is True
    assert snap["values"]["weather_index.temperature.baseline_deviation"] == "2.6"


def test_weather_index_value_key_predicate() -> None:
    tree = {
        "op": "ge",
        "left": {"source": "weather_index", "index_code": "evapotranspiration", "key": "value"},
        "right": 6,
    }
    ctx = _wx_ctx(index_code="evapotranspiration", value=Decimal("7.1"))
    assert evaluate(tree, ctx)[0] is True


def test_weather_index_missing_index_fails_closed() -> None:
    tree = {
        "op": "gt",
        "left": {"source": "weather_index", "index_code": "wind"},
        "right": 2,
    }
    # Context only carries a temperature entry → wind resolves to None → no match.
    assert evaluate(tree, _wx_ctx(deviation=Decimal("3.0")))[0] is False


def _wr_ctx(
    risk_code: str = "powdery_mildew",
    score: int | None = None,
    level: str | None = None,
) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        weather_risks={
            risk_code: WeatherRiskEntry(date=date(2026, 6, 20), score=score, level=level),
        },
    )


def test_parse_weather_risk_ref_defaults_to_score() -> None:
    ref = parse_value_ref({"source": "weather_risk", "risk_code": "powdery_mildew"})
    assert isinstance(ref, WeatherRiskValueRef)
    assert ref.risk_code == "powdery_mildew"
    assert ref.field == "score"


def test_parse_weather_risk_ref_rejects_unknown_field() -> None:
    with pytest.raises(ConditionParseError, match="weather_risk ref 'field'"):
        parse_value_ref({"source": "weather_risk", "risk_code": "anthracnose", "field": "nope"})


def test_parse_weather_risk_ref_requires_risk_code() -> None:
    with pytest.raises(ConditionParseError, match="weather_risk ref missing 'risk_code'"):
        parse_value_ref({"source": "weather_risk", "field": "score"})


def test_weather_risk_score_predicate_fires_and_records_snapshot() -> None:
    # High powdery-mildew pressure: score over the alert threshold.
    tree = {
        "op": "ge",
        "left": {"source": "weather_risk", "risk_code": "powdery_mildew"},
        "right": 70,
    }
    matched, snap = evaluate(tree, _wr_ctx(score=82))
    assert matched is True
    # Ints are recorded raw in the snapshot (only Decimals are stringified).
    assert snap["values"]["weather_risk.powdery_mildew.score"] == 82


def test_weather_risk_level_predicate_matches_categorical() -> None:
    tree = {
        "op": "eq",
        "left": {"source": "weather_risk", "risk_code": "anthracnose", "field": "level"},
        "right": "high",
    }
    ctx = _wr_ctx(risk_code="anthracnose", level="high")
    assert evaluate(tree, ctx)[0] is True


def test_weather_risk_missing_pathogen_fails_closed() -> None:
    tree = {
        "op": "ge",
        "left": {"source": "weather_risk", "risk_code": "fruit_fly"},
        "right": 50,
    }
    # Context only carries a powdery_mildew entry → fruit_fly is None → no match.
    assert evaluate(tree, _wr_ctx(score=90))[0] is False


# ---- date-typed crop attributes -------------------------------------------


def _date_attr_ctx(value: object) -> ConditionContext:
    return ConditionContext(
        block_id="00000000-0000-0000-0000-000000000001",
        crop_attributes={"transplant_date": value},
    )


def _date_tree(op: str, right: str) -> dict:
    return {
        "op": op,
        "left": {"source": "crop_attribute", "code": "transplant_date"},
        "right": right,
    }


def test_date_attribute_compares_against_an_iso_string() -> None:
    # The regression: crop_attribute resolves dates as real `date` objects while
    # a YAML threshold is text. `date < str` raises TypeError, which _compare
    # swallows into False — so every comparison against the four seeded date
    # attributes silently never matched.
    ctx = _date_attr_ctx(date(2024, 3, 1))
    assert evaluate(_date_tree("lt", "2025-01-01"), ctx)[0] is True
    assert evaluate(_date_tree("gt", "2025-01-01"), ctx)[0] is False
    assert evaluate(_date_tree("eq", "2024-03-01"), ctx)[0] is True
    assert evaluate(_date_tree("ge", "2024-03-01"), ctx)[0] is True


def test_date_attribute_accepts_a_timestamp_threshold() -> None:
    ctx = _date_attr_ctx(date(2024, 3, 1))
    assert evaluate(_date_tree("eq", "2024-03-01T00:00:00"), ctx)[0] is True


def test_datetime_value_is_compared_by_its_date() -> None:
    ctx = _date_attr_ctx(datetime(2024, 3, 1, 14, 30, tzinfo=UTC))
    assert evaluate(_date_tree("eq", "2024-03-01"), ctx)[0] is True


def test_unparseable_threshold_still_fails_closed() -> None:
    ctx = _date_attr_ctx(date(2024, 3, 1))
    assert evaluate(_date_tree("lt", "not-a-date"), ctx)[0] is False


def test_a_numeric_string_pair_is_still_compared_numerically() -> None:
    # The date arm must not intercept the numeric path: "9" > "10" as text.
    ctx = ConditionContext(block_id="b1", crop_attributes={"tree_age": Decimal("9")})
    tree = {"op": "lt", "left": {"source": "crop_attribute", "code": "tree_age"}, "right": "10"}
    assert evaluate(tree, ctx)[0] is True
