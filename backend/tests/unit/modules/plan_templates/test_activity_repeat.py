"""Repeating manual tasks (public 0115): input rules, diffs and the seed data."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.plan_templates.revisions import diff_snapshots
from app.modules.plan_templates.schemas import PlanTemplateActivityInput

VERSIONS = Path(__file__).parents[4] / "migrations" / "public" / "versions"


def _input(**kw: object) -> PlanTemplateActivityInput:
    return PlanTemplateActivityInput(activity_type="irrigation", **kw)  # type: ignore[arg-type]


def test_a_repeat_needs_a_count_and_a_unit() -> None:
    assert _input(repeat_count=2, repeat_unit="week").repeat_count == 2
    assert _input().repeat_unit is None
    with pytest.raises(ValidationError):
        _input(repeat_count=2)
    with pytest.raises(ValidationError):
        _input(repeat_unit="month")
    with pytest.raises(ValidationError):
        _input(repeat_count=0, repeat_unit="week")
    with pytest.raises(ValidationError):
        _input(repeat_count=2, repeat_unit="day")


def test_a_new_repeat_shows_as_a_changed_task() -> None:
    old = {"irrigation-1": {"title": "Irrigate"}}  # snapshot from before 0115
    new = {"irrigation-1": {"title": "Irrigate", "repeat_count": 1, "repeat_unit": "week"}}
    diff = diff_snapshots(old, new)
    assert diff["changed"][0]["fields"] == ["repeat_count", "repeat_unit"]
    # A task that stays single is not reported.
    assert diff_snapshots(old, {"irrigation-1": {"title": "Irrigate"}})["changed"] == []


def test_seed_data_names_real_medjool_1_7_tasks() -> None:
    spec = importlib.util.spec_from_file_location("m0115", VERSIONS / "0115_activity_repeat.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = module.load()
    seed = json.loads(
        (VERSIONS / "data" / "0111_medjool_plan_templates_1_7.json").read_text(encoding="utf-8")
    )
    families = {
        "medjool-organic-bearing-eg-1-7": "bearing",
        "medjool-organic-new-planting-eg-1-7": "new_planting",
    }
    assert set(data) == set(families)
    for template_code, rows in data.items():
        codes = {a["code"] for a in seed[families[template_code]]}
        notes = {a["code"]: a["notes"] for a in seed[families[template_code]]}
        for code, (count, unit, basis) in rows.items():
            assert code in codes, (template_code, code)
            assert unit in {"week", "month", "season"}
            assert 1 <= int(count) <= 31
            # Every value is read from the task's own "How often" line.
            assert "How often:" in notes[code], code
            assert str(basis)
