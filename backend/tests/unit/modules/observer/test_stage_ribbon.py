"""The stage ribbon's verdict logic.

The ribbon is the whole point of the Observer overview: an operator reads its
colours before they read anything else. Every test here is about a way the
ribbon could lie — by calling a healthy farm broken, by calling a broken
pipeline healthy, or by inventing a denominator that does not exist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.observer.service import (
    MAX_WINDOW_DAYS,
    WindowTooWideError,
    _build_stages,
    _check_window,
    _empty_overview,
)


def _stages(
    *,
    discovered: int = 100,
    acquired: int = 100,
    failed: int = 0,
    in_flight: int = 0,
    skipped: int = 0,
    computed: int = 100,
    rows: int = 700,
    index_codes: int = 7,
    cells_produced: int = 0,
    cells_expected: int = 0,
    scene_days: int = 50,
    trend_days: int = 50,
    product_ambiguous: bool = False,
    alerts: int = 0,
    recommendations: int = 0,
) -> dict[str, dict]:
    built = _build_stages(
        {
            "discovered": discovered,
            "acquired": acquired,
            "failed": failed,
            "in_flight": in_flight,
            "skipped": skipped,
        },
        {"scenes": computed, "rows": rows, "index_codes": index_codes},
        {"produced": cells_produced, "expected": cells_expected},
        {
            "scene_days": scene_days,
            "trend_days": trend_days,
            "product_ambiguous": product_ambiguous,
        },
        {"alerts": alerts, "recommendations": recommendations},
    )
    return {s["key"]: s for s in built}


def test_a_fully_healthy_pipeline_reads_ok_end_to_end() -> None:
    s = _stages(cells_produced=40, cells_expected=40)
    assert s["acquired"]["verdict"] == "ok"
    assert s["indices"]["verdict"] == "ok"
    assert s["cells"]["verdict"] == "ok"
    assert s["trend"]["verdict"] == "ok"


def test_ungridded_farm_is_not_applicable_not_a_failure() -> None:
    """The regression this denominator exists to prevent.

    813 scenes on blocks with no grid config are not 813 missing cell
    aggregates. Reporting "0 of 1215" would paint an ordinary farm red and
    train operators to ignore the colour.
    """
    s = _stages(computed=1215, cells_produced=0, cells_expected=0)
    assert s["cells"]["verdict"] == "not_applicable"
    assert s["cells"]["expected"] == 0
    assert s["cells"]["shortfall"] == 0


def test_partially_gridded_farm_is_judged_only_on_its_gridded_scenes() -> None:
    # 1,215 scenes, 402 of them on gridded blocks, all 402 produced cells.
    s = _stages(computed=1215, cells_produced=402, cells_expected=402)
    assert s["cells"]["verdict"] == "ok"
    assert s["cells"]["shortfall"] == 0


def test_gridded_scene_that_produced_no_cells_is_a_real_shortfall() -> None:
    """22 of 402 gridded scenes missing cells is flagged, not tinted green."""
    s = _stages(computed=1215, cells_produced=380, cells_expected=402)
    assert s["cells"]["verdict"] == "warn"
    assert s["cells"]["shortfall"] == 22


def test_a_large_cell_shortfall_escalates_from_warn_to_bad() -> None:
    s = _stages(computed=1215, cells_produced=200, cells_expected=402)
    assert s["cells"]["verdict"] == "bad"
    assert s["cells"]["shortfall"] == 202


def test_stale_cagg_shows_as_a_bad_trend_stage() -> None:
    """#336: backfilled history never enters the rolling refresh window.

    The aggregate rows are present and the trend line is missing them. This
    is the single most valuable thing the ribbon surfaces, because nothing
    else in the product notices.
    """
    s = _stages(scene_days=215, trend_days=118)
    assert s["trend"]["verdict"] == "bad"
    assert s["trend"]["shortfall"] == 97


def test_a_scene_landing_between_the_write_and_the_refresh_is_not_flagged() -> None:
    """One straggler out of 215 is normal operation, not a defect.

    If the ribbon went amber for this, operators would learn to ignore amber
    and miss the real staleness above.
    """
    s = _stages(scene_days=215, trend_days=214)
    assert s["trend"]["verdict"] == "ok"


def test_compute_failures_show_at_the_indices_stage_not_the_acquire_stage() -> None:
    """#335: the job says 'succeeded' because the *download* succeeded.

    Acquisition and computation are separate stages precisely so a scene that
    downloaded and then died in compute_indices cannot hide behind a green
    acquire count.
    """
    s = _stages(discovered=1246, acquired=1246, computed=1215)
    assert s["acquired"]["verdict"] == "ok"
    assert s["indices"]["verdict"] == "warn"
    assert s["indices"]["shortfall"] == 31


def test_skipped_scenes_are_removed_from_the_acquire_denominator() -> None:
    """A cloud-skipped scene was never going to be acquired.

    Counting it as a miss would make a cloudy month look like a provider
    outage.
    """
    s = _stages(discovered=100, skipped=20, acquired=80)
    assert s["acquired"]["expected"] == 80
    assert s["acquired"]["verdict"] == "ok"
    assert s["acquired"]["shortfall"] == 0


def test_first_and_last_stages_carry_no_denominator() -> None:
    """Discovered has no predecessor; consumers are not a conversion of scenes.

    Inventing a ratio for either would be a fabricated metric — "64 alerts
    from 1,215 scenes" is not a 5% success rate.
    """
    s = _stages(alerts=41, recommendations=23)
    assert s["discovered"]["expected"] is None
    assert s["discovered"]["verdict"] == "info"
    assert s["consumers"]["expected"] is None
    assert s["consumers"]["verdict"] == "info"
    assert s["consumers"]["count"] == 64
    assert s["consumers"]["detail"] == {"alerts": 41, "recommendations": 23}


def test_trend_stage_carries_the_product_ambiguity_flag() -> None:
    """`block_index_daily` has no product dimension.

    With two products on a block the covered-day count cannot be attributed
    to the selected one, and the UI has to say so rather than overstate it.
    """
    s = _stages(product_ambiguous=True)
    assert s["trend"]["detail"]["product_ambiguous"] is True


def test_empty_overview_is_all_zeros_and_never_reports_a_failure() -> None:
    """A farm with no blocks in scope has nothing wrong with it."""
    now = datetime.now(UTC)
    ov = _empty_overview(uuid4(), now - timedelta(days=30), now)
    assert ov["block_count"] == 0
    verdicts = {s["key"]: s["verdict"] for s in ov["stages"]}
    assert verdicts["cells"] == "not_applicable"
    assert verdicts["trend"] == "not_applicable"
    assert "bad" not in verdicts.values()


# ---- window guard ---------------------------------------------------------


def test_window_must_move_forwards() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="after"):
        _check_window(now, now)
    with pytest.raises(ValueError, match="after"):
        _check_window(now, now - timedelta(days=1))


def test_window_at_the_limit_is_accepted_and_one_day_past_it_is_not() -> None:
    """The overview fires several hypertable aggregates; the cap is the guard."""
    now = datetime.now(UTC)
    _check_window(now - timedelta(days=MAX_WINDOW_DAYS), now)
    with pytest.raises(WindowTooWideError):
        _check_window(now - timedelta(days=MAX_WINDOW_DAYS + 1), now)
