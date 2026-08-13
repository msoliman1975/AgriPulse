"""Pure-function tests for the weather-driven risk models + registry (PR-R1)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.modules.weather.risk import (
    REGISTRY,
    RiskBlockContext,
    RiskLevel,
    RiskWeatherDay,
    applicable_specs,
    evaluate_risks,
)
from app.modules.weather.risk.models import anthracnose, fruit_fly, powdery_mildew


def _dec(v: float | None) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _day(
    i: int,
    *,
    t: float | None = None,
    rh: float | None = None,
    p: float | None = None,
    lwd: float | None = None,
) -> RiskWeatherDay:
    return RiskWeatherDay(
        date=date(2026, 6, 1) + timedelta(days=i),
        temp_mean_c=_dec(t),
        humidity_mean_pct=_dec(rh),
        precip_mm=_dec(p),
        leaf_wetness_hours=_dec(lwd),
    )


def _window(n: int, **kw: float | None) -> list[RiskWeatherDay]:
    return [_day(i, **kw) for i in range(n)]


_MANGO_FRUIT = RiskBlockContext(crop_path="mango.keitt.large", growth_stage="fruit_development")
_MANGO_FLOWER = RiskBlockContext(crop_path="mango", growth_stage="flowering")


# --- Powdery mildew --------------------------------------------------------


def test_powdery_mildew_high_on_warm_humid_dry_window() -> None:
    # 23 C, 75 % RH, no rain — squarely in the favourable band, at a
    # susceptible stage -> saturating pressure.
    score = powdery_mildew(_window(14, t=23, rh=75, p=0), _MANGO_FLOWER)
    assert score is not None
    assert score.risk_code == "powdery_mildew"
    assert score.score == 100
    assert score.level is RiskLevel.high
    assert score.inputs["favorable_days"] == "14"


def test_powdery_mildew_rain_suppresses() -> None:
    # Same warm-humid window but wet every day -> spores washed off -> zero.
    score = powdery_mildew(_window(14, t=23, rh=75, p=5), _MANGO_FLOWER)
    assert score is not None
    assert score.score == 0
    assert score.level is RiskLevel.low


def test_powdery_mildew_off_stage_is_damped_not_zero() -> None:
    # Ideal weather but a non-susceptible stage halves the signal (0.5 factor).
    ctx = RiskBlockContext(crop_path="mango", growth_stage="veg_flush")
    score = powdery_mildew(_window(14, t=23, rh=75, p=0), ctx)
    assert score is not None
    assert score.score == 50
    assert score.level is RiskLevel.moderate


def test_powdery_mildew_unknown_stage_keeps_full_signal() -> None:
    # Graceful degradation: no growth_stage -> weather-only, not suppressed.
    ctx = RiskBlockContext(crop_path="mango", growth_stage=None)
    score = powdery_mildew(_window(14, t=23, rh=75, p=0), ctx)
    assert score is not None
    assert score.score == 100


def test_powdery_mildew_none_without_humidity() -> None:
    # Needs both temp and humidity; a window with no RH cannot be assessed.
    assert powdery_mildew(_window(14, t=23, rh=None, p=0), _MANGO_FLOWER) is None


# --- Anthracnose -----------------------------------------------------------


def test_anthracnose_high_on_warm_wet_window() -> None:
    score = anthracnose(_window(14, t=27, rh=80, p=5), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 100
    assert score.level is RiskLevel.high
    assert score.inputs["wet_days"] == "14"


def test_anthracnose_dry_warm_is_low() -> None:
    # Warm but dry (no rain, RH below the wetness threshold) -> no infection.
    score = anthracnose(_window(14, t=27, rh=50, p=0), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 0
    assert score.level is RiskLevel.low


def test_anthracnose_wetness_via_humidity_alone() -> None:
    # Near-saturated air counts as leaf wetness even without rain.
    score = anthracnose(_window(14, t=27, rh=92, p=0), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 100


# --- Fruit fly -------------------------------------------------------------


def test_fruit_fly_accumulates_degree_days_in_fruit_window() -> None:
    # 25 C, humid: dd = 12/day * 14 = 168; base 168/210 = 0.8 -> 80.
    score = fruit_fly(_window(14, t=25, rh=60), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 80
    assert score.level is RiskLevel.high


def test_fruit_fly_strong_off_stage_damping() -> None:
    # Same DD load but no fruit on the tree -> 0.25 factor -> 80*0.25 = 20.
    ctx = RiskBlockContext(crop_path="mango", growth_stage="pre_flowering")
    score = fruit_fly(_window(14, t=25, rh=60), ctx)
    assert score is not None
    assert score.score == 20
    assert score.level is RiskLevel.low


def test_fruit_fly_dry_air_damps_development() -> None:
    # RH below the boost floor multiplies DD by 0.6: 12*0.6*14=100.8/210=0.48.
    score = fruit_fly(_window(14, t=25, rh=40), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 48
    assert score.level is RiskLevel.moderate


def test_fruit_fly_below_base_temp_scores_zero_not_none() -> None:
    # Cold window: usable days exist but no degree-days accumulate.
    score = fruit_fly(_window(14, t=10, rh=60), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 0


def test_fruit_fly_none_without_temperature() -> None:
    assert fruit_fly(_window(14, t=None, rh=60), _MANGO_FRUIT) is None


def test_moderate_band_lower_cutoff_is_40() -> None:
    # 7 ideal fruit-fly days: dd 12*7=84; base 84/210=0.40 -> exactly 40.
    score = fruit_fly(_window(7, t=25, rh=60), _MANGO_FRUIT)
    assert score is not None
    assert score.score == 40
    assert score.level is RiskLevel.moderate
    # One fewer day drops below the cutoff into "low".
    low = fruit_fly(_window(6, t=25, rh=60), _MANGO_FRUIT)
    assert low is not None
    assert low.score < 40
    assert low.level is RiskLevel.low


# --- Registry --------------------------------------------------------------


def test_registry_prefix_match() -> None:
    assert {s.risk_code for s in applicable_specs("mango")} == {
        "powdery_mildew",
        "anthracnose",
        "fruit_fly",
    }
    # Cultivar descendants match the same mango models.
    assert len(applicable_specs("mango.keitt.large")) == 3
    # A "mangosteen" crop must NOT match the "mango" prefix.
    assert applicable_specs("mangosteen") == []
    # Non-mango crops have no V1 models.
    assert applicable_specs("potato") == []


def test_evaluate_risks_runs_applicable_and_drops_none() -> None:
    # A warm-humid-dry window: PM saturates, anthracnose is dry (0), fruit fly
    # accumulates. All three are applicable to mango and return a score.
    scores = evaluate_risks(_window(14, t=24, rh=70, p=0), _MANGO_FRUIT)
    assert {s.risk_code for s in scores} == {"powdery_mildew", "anthracnose", "fruit_fly"}


def test_evaluate_risks_empty_for_unmodelled_crop() -> None:
    ctx = RiskBlockContext(crop_path="potato", growth_stage="vegetative")
    assert evaluate_risks(_window(14, t=24, rh=70, p=0), ctx) == []


def test_evaluate_risks_accepts_per_model_window_map() -> None:
    # fruit_set is the one stage susceptible to all three models, so each
    # saturates without stage damping.
    ctx = RiskBlockContext(crop_path="mango.keitt.large", growth_stage="fruit_set")
    windows = {
        "powdery_mildew": _window(14, t=23, rh=75, p=0),
        "anthracnose": _window(14, t=27, rh=92, p=0),
        "fruit_fly": _window(14, t=25, rh=60),
    }
    scores = {s.risk_code: s.score for s in evaluate_risks(windows, ctx)}
    assert scores["powdery_mildew"] == 100
    assert scores["anthracnose"] == 100
    assert scores["fruit_fly"] == 80


def test_registry_is_append_only_shape() -> None:
    # Guards the V1 contract: 3 mango models, each a disease/pest kind.
    assert len(REGISTRY) == 3
    assert all(s.crop_prefix == "mango" for s in REGISTRY)
    assert {s.kind for s in REGISTRY} == {"disease", "pest"}


# --- leaf wetness ----------------------------------------------------------
#
# The two foliar models read wetness in OPPOSITE directions, which is the
# whole reason it is worth measuring: a daily mean RH cannot distinguish
# "damp enough for mildew" from "soaked enough to wash mildew off, and to let
# anthracnose infect". These tests pin that opposition.


def test_anthracnose_infects_on_measured_wetness_the_daily_mean_would_miss() -> None:
    """A dry-looking day by mean RH can still hold a long saturated night."""
    # 60% mean RH is well under the 90% proxy threshold, so without measured
    # wetness this window scores zero. Ten wet hours says otherwise.
    warm_dry_looking = _window(10, t=27, rh=60, p=0)
    assert anthracnose(warm_dry_looking, _MANGO_FRUIT).score == 0

    warm_actually_wet = _window(10, t=27, rh=60, p=0, lwd=10)
    scored = anthracnose(warm_actually_wet, _MANGO_FRUIT)
    assert scored.score > 0
    # And the provenance says the verdict rests on measurement, not the proxy.
    assert scored.inputs["measured_wetness_days"] == "10"


def test_anthracnose_needs_a_sustained_wet_spell_not_a_damp_moment() -> None:
    brief = _window(10, t=27, rh=60, p=0, lwd=2)
    assert anthracnose(brief, _MANGO_FRUIT).score == 0


def test_powdery_mildew_is_suppressed_by_the_same_wetness_that_drives_anthracnose() -> None:
    """Free water washes conidia off, so a soaking night protects the crop."""
    favourable = _window(10, t=24, rh=75, p=0)
    baseline = powdery_mildew(favourable, _MANGO_FLOWER).score
    # The suppression below is only meaningful against a non-zero baseline.
    assert baseline > 0

    soaked = _window(10, t=24, rh=75, p=0, lwd=12)
    assert powdery_mildew(soaked, _MANGO_FLOWER).score == 0

    # A merely damp night is still mildew weather — the threshold discriminates.
    damp = _window(10, t=24, rh=75, p=0, lwd=4)
    assert powdery_mildew(damp, _MANGO_FLOWER).score == baseline


def test_missing_leaf_wetness_falls_back_rather_than_reading_as_dry() -> None:
    """`None` means "not measured". Treating it as dry would invent evidence
    of safety for every day projected before the index existed."""
    # High mean RH with no measured wetness must still trigger anthracnose
    # through the legacy proxy path.
    legacy = _window(10, t=27, rh=95, p=0)
    assert all(d.leaf_wetness_hours is None for d in legacy)
    scored = anthracnose(legacy, _MANGO_FRUIT)
    assert scored.score > 0
    assert scored.inputs["measured_wetness_days"] == "0"
