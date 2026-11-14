"""Heat units configured per crop (D17), checked without a database.

The arithmetic (three methods, upper cutoff), the start rules (calendar date,
planting, stage entry, the block's own override), crop -> variety -> strain
inheritance, and the ``{source: heat_units}`` condition source end to end:
parse, evaluate, compile, readiness and evidence labels.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from app.modules.farms.heat_units import (
    HeatUnitConfig,
    accumulate,
    daily_gdd,
    most_recent_mmdd,
    resolve_config,
    resolve_start,
    validate_start,
)
from app.modules.recommendations.folding_compiler import compile_folding_tree
from app.modules.recommendations.readiness import Requirement, assess, extract_requirements
from app.modules.recommendations.schemas import ReadinessRequirement
from app.shared.conditions import ConditionContext, ConditionParseError, evaluate, parse_value_ref
from app.shared.conditions.context import HEAT_UNIT_KEYS
from app.shared.conditions.models import HeatUnitsValueRef
from app.shared.finding_evidence import evidence_label

D = Decimal
_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "public" / "versions"
_TREE = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "trees"
    / "medjool_v2"
    / "date_palm_medjool_data_readiness.definition.json"
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(
    method: str = "mean",
    *,
    base: str = "18",
    upper: str | None = None,
    kind: str | None = "date",
    value: str | None = "01-01",
) -> HeatUnitConfig:
    return HeatUnitConfig(
        method=method,
        start_kind=kind,
        start_value=value,
        base=D(base),
        upper=D(upper) if upper is not None else None,
    )


# ---- daily arithmetic ------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "tmin", "tmax", "upper", "expected"),
    [
        # mean: (Tmax + Tmin) / 2 - base
        ("mean", "20", "36", None, "10"),
        ("mean", "10", "20", None, "0"),  # mean 15 below base 18: floored at 0
        ("mean", "20", "44", "38", "14"),  # mean ignores the upper temperature
        # max: Tmax - base
        ("max", "20", "36", None, "18"),
        ("max", "5", "15", None, "0"),
        # min_max_cutoff: clip both to [base, upper], then mean - base
        ("min_max_cutoff", "20", "44", "38", "11"),  # Tmax 44 held at 38
        ("min_max_cutoff", "10", "30", "38", "6"),  # Tmin 10 raised to base 18
        ("min_max_cutoff", "10", "30", None, "6"),  # no upper: only the base clip
        ("min_max_cutoff", "20", "44", None, "14"),  # no upper: Tmax kept
        ("min_max_cutoff", "5", "12", "38", "0"),  # whole day below base
    ],
)
def test_daily_gdd(method: str, tmin: str, tmax: str, upper: str | None, expected: str) -> None:
    value = daily_gdd(
        method, tmin=D(tmin), tmax=D(tmax), base=D("18"), upper=D(upper) if upper else None
    )
    assert value == D(expected)


def test_daily_gdd_rejects_an_unknown_method() -> None:
    with pytest.raises(ValueError, match="unknown gdd_method"):
        daily_gdd("average", tmin=D("1"), tmax=D("2"), base=D("0"))


# ---- start resolution --------------------------------------------------------


def test_most_recent_mmdd_is_on_or_before_today() -> None:
    today = date(2026, 11, 14)
    assert most_recent_mmdd("03-01", today) == date(2026, 3, 1)
    assert most_recent_mmdd("11-14", today) == today
    assert most_recent_mmdd("12-01", today) == date(2025, 12, 1)


def test_most_recent_29_february_falls_back_to_the_last_leap_year() -> None:
    assert most_recent_mmdd("02-29", date(2026, 11, 14)) == date(2024, 2, 29)
    assert most_recent_mmdd("04-31", date(2026, 11, 14)) is None


def test_resolve_start_by_kind() -> None:
    today = date(2026, 11, 14)
    kwargs: dict[str, Any] = {
        "today": today,
        "planting_date": date(2026, 4, 2),
        "stage_entered": date(2026, 2, 10),
        "override": None,
    }
    assert resolve_start(_config(kind="date", value="03-01"), **kwargs) == date(2026, 3, 1)
    assert resolve_start(_config(kind="planting", value=None), **kwargs) == date(2026, 4, 2)
    assert resolve_start(_config(kind="stage", value="pollination"), **kwargs) == date(2026, 2, 10)
    assert resolve_start(_config(kind=None, value=None), **kwargs) is None


def test_missing_planting_or_stage_entry_has_no_start() -> None:
    kwargs: dict[str, Any] = {
        "today": date(2026, 11, 14),
        "planting_date": None,
        "stage_entered": None,
        "override": None,
    }
    assert resolve_start(_config(kind="planting", value=None), **kwargs) is None
    assert resolve_start(_config(kind="stage", value="pollination"), **kwargs) is None


def test_the_blocks_own_start_wins_over_the_crops_rule() -> None:
    override = date(2026, 3, 20)
    for config in (
        _config(kind="date", value="01-01"),
        _config(kind="stage", value="pollination"),
        _config(kind=None, value=None),
    ):
        start = resolve_start(
            config,
            today=date(2026, 11, 14),
            planting_date=date(2020, 1, 1),
            stage_entered=date(2026, 2, 10),
            override=override,
        )
        assert start == override


# ---- inheritance -------------------------------------------------------------


def _node(**kw: Any) -> SimpleNamespace:
    base = {"gdd_method": None, "gdd_start_kind": None, "gdd_start_value": None}
    return SimpleNamespace(**{**base, **kw})


_CROP = _node(
    gdd_base_temp_c=D("18"),
    gdd_upper_temp_c=D("38"),
    gdd_method="max",
    gdd_start_kind="date",
    gdd_start_value="01-01",
)


def test_crop_alone() -> None:
    cfg = resolve_config(_CROP)
    assert (cfg.method, cfg.start_kind, cfg.start_value) == ("max", "date", "01-01")
    assert (cfg.base, cfg.upper) == (D("18"), D("38"))


def test_deepest_non_null_wins_and_kind_and_value_travel_together() -> None:
    variety = _node(gdd_method="mean", gdd_start_kind="stage", gdd_start_value="pollination")
    strain = _node(gdd_start_kind="planting")
    cfg = resolve_config(_CROP, variety, strain)
    # Method from the variety; start from the strain, with no stale value.
    assert cfg.method == "mean"
    assert (cfg.start_kind, cfg.start_value) == ("planting", None)


def test_a_null_level_inherits_and_base_stays_the_crops() -> None:
    variety = _node(gdd_method="min_max_cutoff")
    cfg = resolve_config(_CROP, variety, _node())
    assert cfg.method == "min_max_cutoff"
    assert (cfg.start_kind, cfg.start_value) == ("date", "01-01")
    assert cfg.base == D("18")


def test_nothing_set_resolves_to_nothing() -> None:
    cfg = resolve_config(_node(gdd_base_temp_c=None, gdd_upper_temp_c=None))
    assert (cfg.method, cfg.start_kind, cfg.base, cfg.upper) == (None, None, None, None)


# ---- accumulation ------------------------------------------------------------


def test_accumulate_sums_from_the_start_and_skips_days_missing_a_temperature() -> None:
    today = date(2026, 3, 5)
    days = [
        (date(2026, 2, 28), D("20"), D("40")),  # before the start: ignored
        (date(2026, 3, 1), D("20"), D("36")),  # 10
        (date(2026, 3, 2), None, D("36")),  # no Tmin: skipped
        (date(2026, 3, 3), D("22"), D("30")),  # 8
        (date(2026, 3, 4), D("19"), None),  # no Tmax: skipped
        (date(2026, 3, 5), D("24"), D("32")),  # 10, today
    ]
    out = accumulate(_config(), start=date(2026, 3, 1), today=today, days=days)
    assert out == {"total": D("28"), "today": D("10"), "days_since_start": 4}


def test_accumulate_without_todays_row_or_any_row() -> None:
    start = date(2026, 3, 1)
    today = date(2026, 3, 3)
    out = accumulate(_config(), start=start, today=today, days=[(start, D("20"), D("36"))])
    assert out == {"total": D("10"), "today": None, "days_since_start": 2}
    empty = accumulate(_config(), start=start, today=today, days=[])
    assert empty == {"total": None, "today": None, "days_since_start": 2}


def test_accumulate_applies_the_upper_cutoff() -> None:
    start = date(2026, 7, 1)
    out = accumulate(
        _config("min_max_cutoff", upper="38"),
        start=start,
        today=start,
        days=[(start, D("26"), D("46"))],
    )
    assert out["total"] == D("14")  # (38 + 26) / 2 - 18


# ---- catalogue validation ------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value"),
    [(None, None), ("planting", None), ("date", "03-01"), ("stage", "pollination")],
)
def test_valid_starts(kind: str | None, value: str | None) -> None:
    validate_start(kind, value)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (None, "03-01"),
        ("planting", "03-01"),
        ("date", None),
        ("date", "3-1"),
        ("date", "13-01"),
        ("stage", None),
        ("stage", "bad code!"),
        ("harvest", None),
    ],
)
def test_invalid_starts(kind: str | None, value: str | None) -> None:
    with pytest.raises(ValueError, match="gdd_start"):
        validate_start(kind, value)


def test_service_merges_a_partial_patch_with_the_row() -> None:
    from app.modules.farms.errors import CropCatalogValidationError
    from app.modules.farms.service import _validate_gdd_start

    row = SimpleNamespace(gdd_start_kind="stage", gdd_start_value="pollination")
    # Switching to planting drops the stage code the request did not resend.
    fields: dict[str, Any] = {"gdd_start_kind": "planting"}
    _validate_gdd_start(fields, existing=row)
    assert fields["gdd_start_value"] is None
    # Switching to a date without one is refused.
    with pytest.raises(CropCatalogValidationError):
        _validate_gdd_start({"gdd_start_kind": "date"}, existing=row)
    # Changing only the value keeps the row's kind.
    _validate_gdd_start({"gdd_start_value": "fruit_set"}, existing=row)
    with pytest.raises(CropCatalogValidationError):
        _validate_gdd_start({"gdd_start_value": "not a code!"}, existing=row)
    # Untouched start: nothing to check.
    _validate_gdd_start({"gdd_method": "mean"}, existing=row)


# ---- the Medjool seed (public 0113) --------------------------------------------


def test_medjool_counts_by_the_mean_from_a_stage_its_calendar_has() -> None:
    seed = _load("0113_crop_heat_units")
    catalogue = _load("0097_medjool_organic_catalogue")
    codes = {s["code"] for s in catalogue.MEDJOOL_STAGES["stages"]}
    assert "pollination" in codes
    assert seed.revision == "0113"
    assert seed.down_revision == "0112"
    validate_start("stage", "pollination")


# ---- the condition source --------------------------------------------------------


def _ctx(heat_units: dict[str, Any] | None = None) -> ConditionContext:
    return ConditionContext.from_block_signals(
        block_id="b1", latest_index_aggregates={}, heat_units=heat_units
    )


_HU = {"total": D("1850.5"), "today": D("12"), "days_since_start": 120}


@pytest.mark.parametrize("key", HEAT_UNIT_KEYS)
def test_parse_every_key(key: str) -> None:
    assert parse_value_ref({"source": "heat_units", "key": key}) == HeatUnitsValueRef(
        source="heat_units", key=key
    )


@pytest.mark.parametrize(
    "raw",
    [{"source": "heat_units"}, {"source": "heat_units", "key": "base18"}],
)
def test_parse_rejects_a_key_outside_the_closed_list(raw: dict[str, Any]) -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref(raw)


def test_evaluates_and_records_the_value() -> None:
    tree = {"op": "ge", "left": {"source": "heat_units", "key": "total"}, "right": 1800}
    matched, snapshot = evaluate(tree, _ctx(_HU))
    assert matched is True
    assert snapshot["values"]["heat_units.total"] == "1850.5"
    days = {"op": "gt", "left": {"source": "heat_units", "key": "days_since_start"}, "right": 90}
    assert evaluate(days, _ctx(_HU))[0] is True


def test_no_heat_units_fails_closed() -> None:
    for op in ("gt", "le"):
        tree = {"op": op, "left": {"source": "heat_units", "key": "total"}, "right": 0}
        assert evaluate(tree, _ctx())[0] is False
    today = {"op": "ge", "left": {"source": "heat_units", "key": "today"}, "right": 0}
    assert evaluate(today, _ctx({**_HU, "today": None}))[0] is False


def test_a_tree_reading_heat_units_compiles_and_needs_them() -> None:
    d = copy.deepcopy(json.loads(_TREE.read_text(encoding="utf-8")))
    d["nodes"]["n_sal"]["condition"]["tree"] = {
        "op": "ge",
        "left": {"source": "heat_units", "key": "total"},
        "right": 1800,
    }
    compiled = compile_folding_tree(d, known_codes=set(d["registers"]))
    assert Requirement("heat_units", "total") in extract_requirements(compiled)


def test_readiness_is_met_when_the_total_is_known() -> None:
    reqs = [Requirement("heat_units", "total")]
    assert assess(reqs, _ctx(_HU))["status"] == "ready"
    missing = assess(reqs, _ctx({"total": None, "today": None, "days_since_start": 3}))
    assert missing["status"] == "not_ready"
    assert missing["missing"] == [{"kind": "heat_units", "key": "total"}]
    ReadinessRequirement(kind="heat_units", key="total")


def test_evidence_labels_in_both_languages() -> None:
    assert evidence_label("heat_units.total") == "Heat units since start"
    assert evidence_label("heat_units.days_since_start", "ar") == (
        "الأيام منذ بداية حساب الوحدات الحرارية"
    )
