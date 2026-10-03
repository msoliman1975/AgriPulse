"""The organic Medjool seed (public 0097 and 0099), checked without a database.

0097 writes the Medjool calendar straight into ``phenology_stages_override``
and so skips the API validator; 0099 anchors template activities to stage
codes and to activity types that the API also validates only on write. A
mistake in either would surface as a template whose activities silently do
not resolve. These tests run the same checks on the literals.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import get_args

from app.modules.farms.phenology import validate_phenology_payload
from app.modules.farms.phenology_advance import stage_for_date
from app.modules.plans.schemas import ActivityType

_VERSIONS = Path(__file__).resolve().parents[3] / "migrations" / "public" / "versions"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CATALOGUE = _load("0097_medjool_organic_catalogue")
_TEMPLATES = _load("0099_medjool_organic_plan_templates")
_STAGES = _CATALOGUE.MEDJOOL_STAGES["stages"]


def test_calendar_passes_the_perennial_validator() -> None:
    validate_phenology_payload(_CATALOGUE.MEDJOOL_STAGES, is_perennial=True, has_gdd_base=False)


def test_every_day_has_exactly_the_manuals_phase() -> None:
    # Manual 12.2: week 1 starts 1 January. Phase boundaries by week.
    expected_starts = {
        date(2027, 1, 1): "dormancy",  # week 1
        date(2027, 2, 5): "pollination",  # week 6
        date(2027, 3, 12): "fruit_set",  # week 11
        date(2027, 4, 16): "kimri",  # week 16
        date(2027, 7, 2): "khalal",  # week 27
        date(2027, 7, 30): "rutab",  # week 31
        date(2027, 8, 27): "tamar",  # week 35
        date(2027, 9, 10): "harvest",  # week 37
        date(2027, 10, 15): "post_harvest",  # week 42
    }
    seen: dict[date, str] = {}
    previous = None
    day = date(2027, 1, 1)
    while day.year == 2027:
        stage = stage_for_date(_STAGES, is_perennial=True, planting_date=None, today=day)
        assert stage is not None, f"{day} resolves to no stage"
        if stage != previous:
            seen[day] = stage
            previous = stage
        day += timedelta(days=1)
    assert seen == expected_starts


def test_no_stage_carries_kc() -> None:
    # The manual gives no crop coefficient.
    assert all("kc" not in s for s in _STAGES)


def test_template_activity_types_are_known() -> None:
    known = set(get_args(ActivityType))
    for row in _TEMPLATES.bearing_rows() + _TEMPLATES.new_planting_rows():
        assert row["activity_type"] in known, row["activity_type"]


def test_bearing_rows_anchor_to_medjool_stages() -> None:
    codes = {s["code"] for s in _STAGES}
    rows = _TEMPLATES.bearing_rows()
    assert len(rows) == 31
    for row in rows:
        assert row["anchor"] == "stage"
        assert row["stage_code"] in codes
        assert row["offset_days"] >= 0
        assert row["duration_days"] >= 1
        assert "Source [" in row["notes"]


def test_bearing_rows_land_on_the_manuals_weeks() -> None:
    starts = {
        s["code"]: date(2027, *map(int, s["advance"]["start_doy"].split("-"))) for s in _STAGES
    }
    for atype, stage, first, last, *_ in _TEMPLATES.BEARING:
        offset, duration = _TEMPLATES._weeks(stage, first, last)
        begin = starts[stage] + timedelta(days=offset)
        end = begin + timedelta(days=duration - 1)
        assert begin == date(2027, 1, 1) + timedelta(weeks=first - 1), (
            atype,
            stage,
            first,
        )
        last_day = (
            date(2027, 12, 31) if last == 52 else date(2027, 1, 1) + timedelta(weeks=last, days=-1)
        )
        assert end == last_day, (atype, stage, last)


def test_new_planting_rows_run_from_week_minus_8_to_year_5() -> None:
    rows = _TEMPLATES.new_planting_rows()
    assert len(rows) == 20
    assert min(r["offset_days"] for r in rows) == -56
    assert max(r["offset_days"] + r["duration_days"] for r in rows) == 5 * 365
    assert all(r["anchor"] == "start" and r["stage_code"] is None for r in rows)


def test_inputs_carry_the_certifier_note() -> None:
    for row in _TEMPLATES.bearing_rows() + _TEMPLATES.new_planting_rows():
        if row["product_name"] and row["activity_type"] in {
            "fertilizing",
            "spraying",
            "soil_prep",
            "bagging",
        }:
            assert "permitted inputs" in row["notes"], row["notes"][:60]
