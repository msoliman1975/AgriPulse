"""Steered incidents: the strength curve, the cell choices, the scenario.

No database. The SQL that moves rows is covered by an integration test;
these pin the parts a wrong answer would hide in, because a ramp that is
off by one day or a scenario that names a block twice moves the wrong
readings and the replay still runs to the end.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.demo_history.incidents import (
    Incident,
    Shift,
    _cell_filter,
    bounds_for,
)
from app.modules.demo_history.scenarios import ewais_grove

SHIFT = (Shift("ndmi", -0.1),)


def _incident(**overrides: object) -> Incident:
    fields: dict[str, object] = {
        "code": "x",
        "title": "x",
        "blocks": ("B01",),
        "start": date(2025, 7, 1),
        "full": date(2025, 7, 5),
        "until": date(2025, 7, 10),
        "gone": date(2025, 7, 20),
        "shifts": SHIFT,
    }
    fields.update(overrides)
    return Incident(**fields)  # type: ignore[arg-type]


def test_weight_is_zero_outside_the_span() -> None:
    inc = _incident()
    assert inc.weight(date(2025, 6, 30)) == 0
    assert inc.weight(date(2025, 7, 20)) == 0


def test_weight_ramps_in_holds_and_ramps_out() -> None:
    inc = _incident()
    assert inc.weight(date(2025, 7, 1)) == 0
    assert inc.weight(date(2025, 7, 3)) == pytest.approx(0.5)
    assert inc.weight(date(2025, 7, 5)) == 1
    assert inc.weight(date(2025, 7, 10)) == 1
    assert inc.weight(date(2025, 7, 15)) == pytest.approx(0.5)


def test_an_incident_at_full_strength_from_its_first_day() -> None:
    inc = _incident(full=date(2025, 7, 1))
    assert inc.weight(date(2025, 7, 1)) == 1


@pytest.mark.parametrize(
    "dates",
    [
        (date(2025, 7, 5), date(2025, 7, 1), date(2025, 7, 10), date(2025, 7, 20)),
        (date(2025, 7, 1), date(2025, 7, 5), date(2025, 7, 20), date(2025, 7, 20)),
    ],
)
def test_dates_out_of_order_are_refused(dates: tuple[date, date, date, date]) -> None:
    start, full, until, gone = dates
    with pytest.raises(ValueError, match="dates must satisfy"):
        _incident(start=start, full=full, until=until, gone=gone)


def test_an_incident_with_no_shift_is_refused() -> None:
    with pytest.raises(ValueError, match="changes nothing"):
        _incident(shifts=())


def test_cell_specs() -> None:
    assert _cell_filter("all") == ("TRUE", {})
    assert _cell_filter("cols:2-4") == ("gc.col_idx BETWEEN :lo AND :hi", {"lo": 2, "hi": 4})
    assert _cell_filter("rows:0-0") == ("gc.row_idx BETWEEN :lo AND :hi", {"lo": 0, "hi": 0})
    assert _cell_filter("share:0.5") == (None, {"share": 0.5})


@pytest.mark.parametrize("spec", ["share:0", "share:1.5", "ring:3", "cols"])
def test_bad_cell_specs_are_refused(spec: str) -> None:
    with pytest.raises(ValueError, match=r"share must be|unknown cells spec|invalid literal"):
        _cell_filter(spec)


def test_thermal_indices_stay_in_their_unit_range() -> None:
    assert bounds_for("smi") == (0.0, 1.0)
    assert bounds_for("cwsi") == (0.0, 1.0)
    assert bounds_for("ndvi") == (-1.0, 1.0)


def test_the_ewais_scenario_is_well_formed() -> None:
    codes = [inc.code for inc in ewais_grove.INCIDENTS]
    assert len(codes) == len(set(codes)), "incident codes must be unique"
    span_start, span_end = date(2024, 9, 29), date(2026, 9, 28)
    for inc in ewais_grove.INCIDENTS:
        assert span_start <= inc.start, inc.code
        assert inc.gone <= span_end + timedelta(days=1), inc.code
        for block in inc.blocks:
            assert block.startswith("B"), (inc.code, block)
            assert 1 <= int(block[1:]) <= 36, (inc.code, block)
        _cell_filter(inc.cells)


def test_an_unknown_shift_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="add or set"):
        Shift("smi", 0.0, mode="multiply")


def test_the_drip_break_is_applied_after_the_cut_it_deepens() -> None:
    """The overshoot on B14 is the cut's 0.015 pulled further toward 0.

    Applied the other way round, the cut would pull the break back up
    into the on-plan band and the critical finding would never fire.
    """
    order = [inc.code for inc in ewais_grove.INCIDENTS]
    assert order.index("cut_ewais_2025") < order.index("drip_break_during_cut_2025")
    b14_cuts = [
        inc for inc in ewais_grove.INCIDENTS if inc.code == "cut_ewais_2025" and "B14" in inc.blocks
    ]
    assert b14_cuts, "B14 must be in the 2025 Ewais cut"


def test_b18_misses_the_2025_cut_only() -> None:
    by_code = {inc.code: inc for inc in ewais_grove.INCIDENTS}
    assert "B18" not in by_code["cut_ewais_2025"].blocks
    assert "B18" in by_code["cut_ewais_2026"].blocks
