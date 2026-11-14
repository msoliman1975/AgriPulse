"""Trees read the crop's reference values (D18): parse, evaluate, compile, readiness."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.recommendations.folding_compiler import (
    FoldingCompileError,
    compile_folding_tree,
)
from app.modules.recommendations.readiness import Requirement, assess, extract_requirements
from app.modules.reference_values.snapshot import load_reference_snapshot
from app.shared.conditions import ConditionContext, ConditionParseError, evaluate, parse_value_ref
from app.shared.conditions.models import ReferenceValueRef

_TREE = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "trees"
    / "medjool_v2"
    / "date_palm_medjool_data_readiness.definition.json"
)

_ECE = {"value": Decimal("4"), "value_min": None, "value_max": None}
_YIELD = {"value": None, "value_min": Decimal("60"), "value_max": Decimal("72")}


def _ctx(reference_values: dict[str, Any] | None = None) -> ConditionContext:
    return ConditionContext.from_block_signals(
        block_id="b1",
        latest_index_aggregates={},
        reference_values=reference_values,
    )


# ---- parse ---------------------------------------------------------------


def test_parse_defaults_the_field_to_value() -> None:
    ref = parse_value_ref({"source": "reference", "key": "soil_ece_threshold_ds_m"})
    assert ref == ReferenceValueRef(
        source="reference", key="soil_ece_threshold_ds_m", field="value"
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"source": "reference"},
        {"source": "reference", "key": ""},
        {"source": "reference", "key": "yield_per_plant_kg", "field": "median"},
    ],
)
def test_parse_rejects_a_missing_key_or_unknown_field(raw: dict[str, Any]) -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref(raw)


# ---- evaluate --------------------------------------------------------------


def test_compares_against_the_crops_value_and_records_it() -> None:
    tree = {
        "op": "lt",
        "left": {"source": "reference", "key": "soil_ece_threshold_ds_m"},
        "right": 5,
    }
    matched, snapshot = evaluate(tree, _ctx({"soil_ece_threshold_ds_m": _ECE}))
    assert matched is True
    assert snapshot["values"]["reference.soil_ece_threshold_ds_m.value"] == "4"


def test_reads_either_end_of_a_range() -> None:
    ctx = _ctx({"yield_per_plant_kg": _YIELD})
    low = {
        "op": "eq",
        "left": {"source": "reference", "key": "yield_per_plant_kg", "field": "value_min"},
        "right": 60,
    }
    high = {
        "op": "eq",
        "left": {"source": "reference", "key": "yield_per_plant_kg", "field": "value_max"},
        "right": 72,
    }
    assert evaluate(low, ctx)[0] is True
    assert evaluate(high, ctx)[0] is True


def test_a_value_the_crop_does_not_set_fails_closed() -> None:
    gt = {"op": "gt", "left": {"source": "reference", "key": "fruit_weight_g"}, "right": 0}
    le = {"op": "le", "left": {"source": "reference", "key": "fruit_weight_g"}, "right": 0}
    assert evaluate(gt, _ctx({"soil_ece_threshold_ds_m": _ECE}))[0] is False
    assert evaluate(le, _ctx({"soil_ece_threshold_ds_m": _ECE}))[0] is False
    # A range has no single value either.
    single = {"op": "gt", "left": {"source": "reference", "key": "yield_per_plant_kg"}, "right": 0}
    assert evaluate(single, _ctx({"yield_per_plant_kg": _YIELD}))[0] is False


# ---- compile -----------------------------------------------------------------


def _tree_reading(ref: dict[str, Any]) -> dict[str, Any]:
    """The data readiness tree with its salinity check reading ``ref`` instead."""
    d = json.loads(_TREE.read_text(encoding="utf-8"))
    d = copy.deepcopy(d)
    d["nodes"]["n_sal"]["condition"]["tree"] = {"op": "gt", "left": ref, "right": 0}
    return d


def test_a_known_key_compiles_and_becomes_a_readiness_requirement() -> None:
    d = _tree_reading({"source": "reference", "key": "soil_ece_threshold_ds_m"})
    compiled = compile_folding_tree(d, known_codes=set(d["registers"]))
    assert Requirement("reference", "soil_ece_threshold_ds_m") in extract_requirements(compiled)


def test_an_unknown_key_does_not_compile() -> None:
    d = _tree_reading({"source": "reference", "key": "soil_ece_threshhold"})
    with pytest.raises(FoldingCompileError) as exc:
        compile_folding_tree(d, known_codes=set(d["registers"]))
    assert "soil_ece_threshhold" in str(exc.value.errors)


# ---- readiness -----------------------------------------------------------------


def test_readiness_counts_a_value_or_a_range_as_set() -> None:
    reqs = [
        Requirement("reference", "soil_ece_threshold_ds_m"),
        Requirement("reference", "yield_per_plant_kg"),
    ]
    both = assess(reqs, _ctx({"soil_ece_threshold_ds_m": _ECE, "yield_per_plant_kg": _YIELD}))
    assert both["status"] == "ready"
    one = assess(reqs, _ctx({"soil_ece_threshold_ds_m": _ECE}))
    assert one["status"] == "partial"
    assert one["missing"] == [{"kind": "reference", "key": "yield_per_plant_kg"}]


# ---- snapshot ------------------------------------------------------------------


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(type("R", (), {"_mapping": r})() for r in self._rows)


class _Session:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.params: dict[str, Any] | None = None

    async def execute(self, _stmt: Any, params: dict[str, Any]) -> _Rows:
        self.params = params
        return _Rows(self.rows)


async def test_snapshot_resolves_the_deepest_path_as_decimals() -> None:
    session = _Session(
        [
            {"crop_path": "date_palm", "key": "soil_ece_threshold_ds_m", "value": 4,
             "value_min": None, "value_max": None},  # fmt: skip
            {"crop_path": "date_palm", "key": "fruit_weight_g", "value": 15,
             "value_min": None, "value_max": None},  # fmt: skip
            {"crop_path": "date_palm.medjool", "key": "fruit_weight_g", "value": Decimal("20"),
             "value_min": Decimal("18"), "value_max": Decimal("28")},  # fmt: skip
        ]
    )
    snap = await load_reference_snapshot(session, crop_path="date_palm.medjool")  # type: ignore[arg-type]
    assert session.params == {"chain": ["date_palm", "date_palm.medjool"]}
    assert snap["soil_ece_threshold_ds_m"] == {
        "value": Decimal("4"),
        "value_min": None,
        "value_max": None,
    }
    assert snap["fruit_weight_g"] == {
        "value": Decimal("20"),
        "value_min": Decimal("18"),
        "value_max": Decimal("28"),
    }


async def test_snapshot_is_empty_for_a_block_with_no_crop() -> None:
    session = _Session([])
    assert await load_reference_snapshot(session, crop_path=None) == {}  # type: ignore[arg-type]
    assert session.params is None
