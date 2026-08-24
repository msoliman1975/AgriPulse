"""Pin the mango phenology curves that migration 0073 writes.

The daily auto-advance task resolves a block's stage by asking which window
contains today. A gap in the calendar means `stage_for_date` returns None and
the block silently holds whatever stage it had, sometimes for weeks; an
overlap means two stages match and the resolver has to pick. Neither is
caught by `validate_phenology_payload`, which only checks shape, unique codes
and unique orders.

So the payloads are checked here directly, without a database: every day of a
leap year must land in exactly one stage, for the generic mango curve and for
the Keitt override. The old 0033 curves are checked the same way, because the
migration restores them on downgrade and a downgrade into a broken calendar
would be worse than the upgrade it undoes.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.modules.farms.phenology import validate_phenology_payload
from app.modules.farms.phenology_advance import stage_for_date

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "public"
    / "versions"
    / "0073_mango_maturation_stage.py"
)


def _load_migration() -> Any:
    spec = importlib.util.spec_from_file_location("mig_0073", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_M = _load_migration()

_CURVES = {
    "mango (new)": _M._MANGO_STAGES_NEW,
    "keitt (new)": _M._KEITT_STAGES_NEW,
    "mango (0033, restored on downgrade)": _M._MANGO_STAGES_OLD,
    "keitt (0033, restored on downgrade)": _M._KEITT_STAGES_OLD,
}


def _every_day_of_a_leap_year() -> list[date]:
    """2024 so 29 February is included — a window boundary written as a
    day-of-month string must not fall into the gap that a non-leap year
    hides."""
    start = date(2024, 1, 1)
    return [start + timedelta(days=n) for n in range(366)]


@pytest.mark.parametrize("name", sorted(_CURVES))
def test_curve_passes_the_platform_validator(name: str) -> None:
    validate_phenology_payload(_CURVES[name], is_perennial=True, has_gdd_base=False)


@pytest.mark.parametrize("name", sorted(_CURVES))
def test_every_day_of_the_year_resolves_to_exactly_one_stage(name: str) -> None:
    stages = _CURVES[name]["stages"]
    unresolved: list[date] = []
    for day in _every_day_of_a_leap_year():
        resolved = stage_for_date(stages, is_perennial=True, planting_date=None, today=day)
        if resolved is None:
            unresolved.append(day)
    assert unresolved == [], f"{name}: {len(unresolved)} days match no stage"


@pytest.mark.parametrize("name", sorted(_CURVES))
def test_no_two_stages_claim_the_same_day(name: str) -> None:
    """`stage_for_date` returns one code even when two windows overlap, so
    the overlap has to be looked for directly."""
    stages = _CURVES[name]["stages"]
    for day in _every_day_of_a_leap_year():
        matched = [
            s["code"]
            for s in stages
            if stage_for_date([s], is_perennial=True, planting_date=None, today=day)
        ]
        assert len(matched) == 1, f"{name}: {day} matches {matched}"


def test_maturation_covers_the_egyptian_harvest_months() -> None:
    """July to mid-September for the generic curve. The commercial harvest
    runs across those months, and the stage exists so the index guide's
    "Maturity/Harvest" bands and the 0064 Kc value of 0.85 have something to
    attach to."""
    stages = _M._MANGO_STAGES_NEW["stages"]
    for day in (date(2024, 7, 1), date(2024, 8, 15), date(2024, 9, 15)):
        assert (
            stage_for_date(stages, is_perennial=True, planting_date=None, today=day) == "maturation"
        )
    # 30 June is still fruit development; 16 September is already the flush.
    assert (
        stage_for_date(stages, is_perennial=True, planting_date=None, today=date(2024, 6, 30))
        == "fruit_development"
    )
    assert (
        stage_for_date(stages, is_perennial=True, planting_date=None, today=date(2024, 9, 16))
        == "post_harvest_flush"
    )


def test_keitt_maturation_sits_later_than_the_generic_one() -> None:
    """Keitt is a late cultivar, picked in September and October. On 1 July a
    generic mango is ripening and a Keitt is still filling fruit."""
    generic = _M._MANGO_STAGES_NEW["stages"]
    keitt = _M._KEITT_STAGES_NEW["stages"]
    july = date(2024, 7, 1)
    assert (
        stage_for_date(generic, is_perennial=True, planting_date=None, today=july) == "maturation"
    )
    assert (
        stage_for_date(keitt, is_perennial=True, planting_date=None, today=july)
        == "fruit_development"
    )
    october = date(2024, 10, 15)
    assert (
        stage_for_date(keitt, is_perennial=True, planting_date=None, today=october) == "maturation"
    )


def test_the_new_curves_add_maturation_and_keep_every_old_code() -> None:
    """Nothing may lose a stage code: two plan templates and three disease
    models are keyed on these strings."""
    for new, old in (
        (_M._MANGO_STAGES_NEW, _M._MANGO_STAGES_OLD),
        (_M._KEITT_STAGES_NEW, _M._KEITT_STAGES_OLD),
    ):
        new_codes = {s["code"] for s in new["stages"]}
        old_codes = {s["code"] for s in old["stages"]}
        assert new_codes == old_codes | {"maturation"}
