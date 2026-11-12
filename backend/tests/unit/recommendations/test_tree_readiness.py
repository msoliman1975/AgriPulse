"""Tree readiness (D15): requirements come from the definition, status from the block."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from app.modules.recommendations.folding_compiler import compile_folding_tree
from app.modules.recommendations.readiness import (
    Requirement,
    assess,
    extract_requirements,
    summarise,
)
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import (
    IndicesEntry,
    SignalEntry,
    WaterBalanceEntry,
    WeatherSnapshot,
)

_TREES = Path(__file__).resolve().parents[4] / "docs" / "trees" / "medjool_v2"


def _compiled(code: str) -> dict:
    d = json.loads((_TREES / f"{code}.definition.json").read_text(encoding="utf-8"))
    return compile_folding_tree(d, known_codes=set(d["registers"]))


def test_requirements_come_from_the_definition() -> None:
    reqs = extract_requirements(_compiled("date_palm_medjool_rpw_risk"))
    kinds = {r.kind for r in reqs}
    assert Requirement("crop_attribute", "palm_phase") in reqs
    assert Requirement("signal", "date_rpw_trap_catch_value") in reqs
    assert Requirement("signal", "date_rpw_inspection_done") in reqs
    assert "params" not in kinds
    # Ordered: block and crop fields before signals, weather last.
    order = [r.kind for r in reqs]
    assert order == sorted(
        order,
        key=[
            "block_field",
            "crop_attribute",
            "signal",
            "water_balance",
            "index",
            "grid",
            "weather",
        ].index,
    )


def test_weather_is_one_requirement_however_many_fields() -> None:
    reqs = extract_requirements(_compiled("date_palm_medjool_cold"))
    assert reqs.count(Requirement("weather", "farm")) == 1
    assert {r.kind for r in reqs} == {"weather"}


def test_compiled_tree_keeps_the_readiness_note() -> None:
    d = json.loads((_TREES / "date_palm_medjool_cold.definition.json").read_text(encoding="utf-8"))
    d["readiness_note_en"] = "Needs the farm's weather."
    d["readiness_note_ar"] = "تحتاج إلى طقس المزرعة."
    compiled = compile_folding_tree(d, known_codes=set(d["registers"]))
    assert compiled["readiness_note_en"] == "Needs the farm's weather."
    assert compiled["readiness_note_ar"] == "تحتاج إلى طقس المزرعة."


_REQS = [
    Requirement("block_field", "salinity_class"),
    Requirement("crop_attribute", "palm_phase"),
    Requirement("signal", "date_bunches_scouted"),
    Requirement("index", "ndvi"),
    Requirement("water_balance", "balance"),
    Requirement("grid", "ndvi"),
    Requirement("weather", "farm"),
]


def _ctx(**kw: object) -> ConditionContext:
    return ConditionContext(block_id="b", **kw)  # type: ignore[arg-type]


def test_a_block_with_everything_is_ready() -> None:
    now = datetime.now(UTC)
    ctx = _ctx(
        block_attributes={"salinity_class": "non_saline"},
        crop_attributes={"palm_phase": "bearing"},
        signals={"date_bunches_scouted": SignalEntry(time=now, days_since_latest=Decimal(3))},
        indices={"ndvi": IndicesEntry(time=now, mean=Decimal("0.4"), baseline_deviation=None)},
        water_balance=WaterBalanceEntry(
            date=date.today(), balance_mm=Decimal(1), irrigation_logged=True
        ),
        weather=WeatherSnapshot(),
    )
    out = assess(_REQS, ctx, has_grid=True)
    assert out["status"] == "ready"
    assert out["met"] == out["total"] == 7
    assert out["missing"] == []


def test_a_block_with_nothing_is_not_ready() -> None:
    out = assess(_REQS, _ctx())
    assert out["status"] == "not_ready"
    assert len(out["missing"]) == 7


def test_some_missing_is_partial_and_lists_what() -> None:
    now = datetime.now(UTC)
    ctx = _ctx(
        crop_attributes={"palm_phase": "juvenile"},
        weather=WeatherSnapshot(),
        # An answer past its window keeps its time but no value (D6): missing.
        signals={"date_bunches_scouted": SignalEntry(time=now)},
        indices={"ndvi": IndicesEntry(time=now, mean=None, baseline_deviation=None)},
    )
    out = assess(_REQS, ctx)
    assert out["status"] == "partial"
    assert {(m["kind"], m["key"]) for m in out["missing"]} == {
        ("block_field", "salinity_class"),
        ("signal", "date_bunches_scouted"),
        ("index", "ndvi"),
        ("water_balance", "balance"),
        ("grid", "ndvi"),
    }


def test_a_tree_that_reads_no_block_data_is_ready() -> None:
    assert assess([], _ctx())["status"] == "ready"


def test_summary_counts() -> None:
    rows = [{"status": "ready"}, {"status": "partial"}, {"status": "partial"}]
    assert summarise(rows) == {"ready": 1, "partial": 2, "not_ready": 0}
