"""Evaluate the seeded date-palm decision trees.

Date palm is the catalog's clearest case of a risk whose *severity* is
phenological rather than just its trigger: identical forecast rain is a
grading nuisance at Kimri and a crop-destroying rot event at Rutab. The
tests that matter here are the ones that pin that ordering, and the one
that pins date palm's salinity threshold apart from potato's — sharing a
single salinity rule across both crops would be wrong in both directions.

Pure evaluation, no database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.modules.recommendations.engine import EvaluationResult, evaluate_tree
from app.modules.recommendations.loader import compile_tree
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import SignalEntry, WeatherSnapshot

_SEEDS = Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"


def _tree(name: str) -> dict:
    return compile_tree(
        yaml.safe_load((_SEEDS / name).read_text(encoding="utf-8")), source_path=name
    )


def _leaf(result: EvaluationResult) -> str:
    return result.path[-1].node_id


def _d(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


# ---------------------------------------------------------------------------
# Ripening rain / humidity
# ---------------------------------------------------------------------------

_RAIN = _tree("date_palm_ripening_rain_risk_v1.yaml")


def _rain_ctx(
    *, stage: str | None, rain_mm: float = 0.0, humidity: float = 30.0
) -> ConditionContext:
    return ConditionContext(
        block_id="b1",
        block_attributes={} if stage is None else {"growth_stage": stage},
        weather=WeatherSnapshot(
            forecast_72h={
                "precipitation_mm_total": _d(rain_mm),
                "humidity_pct_mean": _d(humidity),
            }
        ),
    )


@pytest.mark.parametrize("stage", ["rutab", "tamar"])
def test_rain_at_rutab_or_tamar_is_critical(stage: str) -> None:
    r = evaluate_tree(_RAIN, _rain_ctx(stage=stage, rain_mm=12.0))
    assert _leaf(r) == "leaf_rain_critical"
    assert r.outcome.severity == "critical"


@pytest.mark.parametrize("stage", ["kimri", "khalal"])
def test_rain_at_kimri_or_khalal_is_a_cracking_warning(stage: str) -> None:
    r = evaluate_tree(_RAIN, _rain_ctx(stage=stage, rain_mm=12.0))
    assert _leaf(r) == "leaf_rain_cracking"
    assert r.outcome.severity == "warning"


def test_identical_rain_escalates_from_warning_to_critical_with_stage() -> None:
    """FAO's ordering, encoded: the same forecast is a grading nuisance
    while the fruit is green and a crop-destroying rot event once it is
    soft-ripe. A stage-blind rule cannot express this."""
    kimri = evaluate_tree(_RAIN, _rain_ctx(stage="kimri", rain_mm=12.0))
    rutab = evaluate_tree(_RAIN, _rain_ctx(stage="rutab", rain_mm=12.0))

    assert kimri.outcome.severity == "warning"
    assert rutab.outcome.severity == "critical"


def test_dry_forecast_is_silent_even_at_the_most_sensitive_stage() -> None:
    r = evaluate_tree(_RAIN, _rain_ctx(stage="rutab", rain_mm=0.0, humidity=25.0))
    assert _leaf(r) == "leaf_no_action"


def test_humid_air_without_rain_warns_only_in_the_fungal_window() -> None:
    """Humidity alone is a Khalal/Rutab concern (spoilage, Blacknose); at
    Kimri with no rain there is nothing to say."""
    khalal = evaluate_tree(_RAIN, _rain_ctx(stage="khalal", rain_mm=0.0, humidity=75.0))
    assert _leaf(khalal) == "leaf_humidity_warning"

    kimri = evaluate_tree(_RAIN, _rain_ctx(stage="kimri", rain_mm=0.0, humidity=75.0))
    assert _leaf(kimri) == "leaf_no_action"


@pytest.mark.parametrize("stage", ["dormancy", "pollination", "fruit_set"])
def test_rain_outside_the_ripening_stages_is_ignored(stage: str) -> None:
    r = evaluate_tree(_RAIN, _rain_ctx(stage=stage, rain_mm=30.0, humidity=90.0))
    assert _leaf(r) == "leaf_out_of_window"


def test_rain_tree_fails_closed_without_a_resolved_stage() -> None:
    assert _leaf(evaluate_tree(_RAIN, _rain_ctx(stage=None, rain_mm=30.0))) == "leaf_out_of_window"


def test_rain_tree_fails_closed_without_a_forecast() -> None:
    """A block whose farm has no weather provider yet must not alert."""
    ctx = ConditionContext(block_id="b1", block_attributes={"growth_stage": "rutab"})
    assert _leaf(evaluate_tree(_RAIN, ctx)) == "leaf_no_action"


# ---------------------------------------------------------------------------
# Salinity — the tolerant-crop counterpart to potato_soil_salinity_v1
# ---------------------------------------------------------------------------

_SALT = _tree("date_palm_soil_salinity_v1.yaml")
_POTATO_SALT = _tree("potato_soil_salinity_v1.yaml")


def _salt_ctx(ece: float | None) -> ConditionContext:
    signals = {}
    if ece is not None:
        signals["soil_salinity"] = SignalEntry(time=datetime.now(UTC), value_numeric=_d(ece))
    return ConditionContext(block_id="b1", signals=signals)


def test_salinity_below_the_tolerant_threshold_is_silent() -> None:
    assert _leaf(evaluate_tree(_SALT, _salt_ctx(3.5))) == "leaf_no_action"


def test_salinity_above_threshold_warns() -> None:
    r = evaluate_tree(_SALT, _salt_ctx(6.0))
    assert _leaf(r) == "leaf_moderate"
    assert r.outcome.severity == "warning"


def test_salinity_past_the_25_percent_loss_point_is_critical() -> None:
    r = evaluate_tree(_SALT, _salt_ctx(12.0))
    assert _leaf(r) == "leaf_severe"
    assert r.outcome.severity == "critical"


def test_date_palm_tolerates_salinity_that_already_stresses_potato() -> None:
    """FAO-29 rates date palm tolerant at ECe 4.0 and potato sensitive at
    1.7. At 3.5 dS/m the same block is a warning for potato and a
    non-event for date palm — which is why salinity thresholds are
    per-crop and not one shared rule."""
    ece = 3.5
    assert _leaf(evaluate_tree(_SALT, _salt_ctx(ece))) == "leaf_no_action"
    assert evaluate_tree(_POTATO_SALT, _salt_ctx(ece)).outcome.action_type != "no_action"


def test_salinity_reports_no_data_rather_than_safety() -> None:
    assert _leaf(evaluate_tree(_SALT, _salt_ctx(None))) == "leaf_no_data"


# ---------------------------------------------------------------------------
# Pollination-window rain
# ---------------------------------------------------------------------------

_POLLEN = _tree("date_palm_pollination_rain_v1.yaml")


def _pollen_ctx(*, stage: str, rain_mm: float) -> ConditionContext:
    return ConditionContext(
        block_id="b1",
        block_attributes={"growth_stage": stage},
        weather=WeatherSnapshot(forecast_24h={"precipitation_mm_total": _d(rain_mm)}),
    )


def test_rain_during_pollination_warns() -> None:
    r = evaluate_tree(_POLLEN, _pollen_ctx(stage="pollination", rain_mm=6.0))
    assert _leaf(r) == "leaf_rain_in_window"
    assert r.outcome.severity == "warning"
    # The evidence is split on whether rain destroys set, so this must
    # stay a warning to re-time and verify, never a critical alert.
    assert r.outcome.severity != "critical"


def test_dry_pollination_window_is_silent() -> None:
    assert _leaf(evaluate_tree(_POLLEN, _pollen_ctx(stage="pollination", rain_mm=0.0))) == (
        "leaf_no_action"
    )


@pytest.mark.parametrize("stage", ["dormancy", "kimri", "rutab"])
def test_pollination_tree_only_fires_in_its_own_stage(stage: str) -> None:
    r = evaluate_tree(_POLLEN, _pollen_ctx(stage=stage, rain_mm=20.0))
    assert _leaf(r) == "leaf_out_of_window"


# ---------------------------------------------------------------------------
# KB P1 contract
# ---------------------------------------------------------------------------

_ALL = pytest.mark.parametrize(
    "name",
    [
        "date_palm_ripening_rain_risk_v1.yaml",
        "date_palm_soil_salinity_v1.yaml",
        "date_palm_pollination_rain_v1.yaml",
    ],
)


@_ALL
def test_seed_targets_date_palm_and_carries_provenance(name: str) -> None:
    compiled = _tree(name)
    assert compiled["evidence"]["citations"], "a scientific KB seed must cite its thresholds"
    assert compiled["evidence"]["notes"], "uncertainty must be stated, not omitted"
    assert set(compiled["transferability"]) >= {"egypt", "middle_east", "global"}


@_ALL
def test_actionable_leaves_carry_horizoned_actions(name: str) -> None:
    for node_id, node in _tree(name)["nodes"].items():
        outcome = node.get("outcome")
        if not outcome or outcome["action_type"] == "no_action":
            continue
        assert outcome.get("actions"), f"{node_id} is actionable but carries no actions block"
