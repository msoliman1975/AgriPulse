"""The Medjool 1.7 plan-template seed (public 0111) is consistent with the platform.

Checked offline against the files the migration reads, so a bad row fails CI
instead of the migration in production.
"""

from __future__ import annotations

import importlib.util
import json
import typing
from pathlib import Path

import pytest

from app.modules.plan_templates.schemas import DoseUnit
from app.modules.plans.schemas import ActivityType

_VERSIONS = Path(__file__).resolve().parents[4] / "migrations" / "public" / "versions"
_STAGES = {
    "dormancy",
    "pollination",
    "fruit_set",
    "kimri",
    "khalal",
    "rutab",
    "tamar",
    "harvest",
    "post_harvest",
}


def _migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "m0111", _VERSIONS / "0111_medjool_plan_templates_1_7.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _input_codes() -> set[str]:
    data = json.loads((_VERSIONS / "data" / "0108_medjool_inputs.json").read_text("utf-8"))
    return {i["code"] for i in data["inputs"]}


def _manual_refs() -> set[int]:
    data = json.loads((_VERSIONS / "data" / "0105_sources_library.json").read_text("utf-8"))
    return {
        n for s in data["sources"] for doc, n in s["aliases"] if doc == "medjool_manual_1_7"
    }


@pytest.fixture(scope="module")
def m():  # type: ignore[no-untyped-def]
    return _migration()


def test_data_file_ends_with_a_newline(m) -> None:  # type: ignore[no-untyped-def]
    assert m._DATA.read_text("utf-8").endswith("\n")


@pytest.mark.parametrize("key", ["bearing", "new_planting"])
def test_every_row_uses_known_values(m, key: str) -> None:  # type: ignore[no-untyped-def]
    activity_types = set(typing.get_args(ActivityType))
    dose_units = set(typing.get_args(DoseUnit))
    inputs = _input_codes()
    refs = _manual_refs()
    rows = m.activity_rows(key)
    assert rows, key

    codes = [r["code"] for r in rows]
    assert len(codes) == len(set(codes)), "activity codes must be unique in a template"
    for r in rows:
        where = f"{key}/{r['code']}"
        assert r["activity_type"] in activity_types, where
        assert r["title"] and r["title_ar"], where
        assert r["notes"] and r["notes_ar"], where
        assert r["duration_days"] >= 1, where
        if key == "bearing":
            assert r["stage_code"] in _STAGES, where
            assert r["offset_days"] >= 0, where
        else:
            assert r["stage_code"] is None, where
        if r["input_code"] is not None:
            assert r["input_code"] in inputs, where
        if r["dose_unit"] is not None:
            assert r["dose_unit"] in dose_units, where
            assert r["dose_value"] is not None or r["dose_value_max"] is not None, where
        if r["dose_value"] is not None and r["dose_value_max"] is not None:
            assert r["dose_value"] <= r["dose_value_max"], where
        assert r["source_refs"], f"{where}: every activity names its sources"
        unknown = set(r["source_refs"]) - refs
        assert not unknown, f"{where}: manual refs {unknown} are not in the sources library"
        assert r["confidence"] in {"high", "medium", "low", "expert_inference"}, where


def test_bearing_notes_carry_the_week_prefix(m) -> None:  # type: ignore[no-untyped-def]
    for r in m.activity_rows("bearing"):
        assert r["notes"].startswith(("Week ", "Weeks ")), r["code"]
