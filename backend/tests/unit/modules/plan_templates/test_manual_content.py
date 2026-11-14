"""Agri Operation PR 1: activity codes and evidence tags."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from app.modules.plan_templates.service import assign_activity_codes

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations"
    / "public"
    / "versions"
    / "0104_operation_manual_content.py"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0104", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_assign_codes_numbers_by_type_and_keeps_given_codes() -> None:
    acts = [
        {"activity_type": "spraying", "code": None},
        {"activity_type": "spraying", "code": "spraying-1"},
        {"activity_type": "irrigation", "code": None},
        {"activity_type": "spraying", "code": None},
    ]
    assign_activity_codes(acts)
    assert [a["code"] for a in acts] == ["spraying-2", "spraying-1", "irrigation-1", "spraying-3"]


def test_assign_codes_are_unique() -> None:
    acts = [{"activity_type": "pruning", "code": None} for _ in range(5)]
    assign_activity_codes(acts)
    assert len({a["code"] for a in acts}) == 5


def test_tier_from_notes_takes_the_first_tag() -> None:
    tier = _migration().tier_from_notes
    assert tier("Annual N 360 kg/ha. [EG-FAO]") == "eg_fao"
    assert tier("Trial. [EG] 4-season Dakahlia trial.") == "eg"
    assert tier("Seed rate historical. [GENERIC-HIST]") == "generic"
    assert tier("1st N dose. [EG]/[EG-FAO]") == "eg"
    assert tier("Remove dead wood.") is None
    assert tier(None) is None


def test_backfill_titles_cover_every_seeded_activity() -> None:
    m = _migration()
    assert sorted(m.MANGO) == list(range(1, 17))
    assert sorted(m.POTATO) == list(range(1, 13))
    assert sorted(m.MEDJOOL_BEARING) == list(range(1, 32))
    assert sorted(m.MEDJOOL_NEW) == list(range(1, 21))
    for titles in (m.MANGO, m.POTATO, m.MEDJOOL_BEARING, m.MEDJOOL_NEW):
        for title, title_ar in titles.values():
            assert title
            assert title_ar


def test_arabic_data_covers_every_seeded_activity() -> None:
    path = _MIGRATION.parent / "0110_operation_manual_arabic.py"
    spec = importlib.util.spec_from_file_location("m0110", path)
    assert spec is not None
    assert spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    data = m.load()
    assert {k: len(v) for k, v in data.items()} == {
        "mango": 16,
        "potato": 12,
        "medjool_bearing": 31,
        "medjool_new": 20,
    }
    for family, rows in data.items():
        assert family in m.FAMILIES
        for values in rows.values():
            assert len(values) == 3
            assert values[2]  # every activity has Arabic notes
            assert "[EG" not in values[2]
            assert "[GENERIC" not in values[2]
