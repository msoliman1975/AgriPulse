"""Evaluate the stage-gated potato petiole-nutrient trees (KB content track).

These are the first seeds whose thresholds move with `block.growth_stage`,
so the interesting assertions are the ones where the *same* reading walks to
a different leaf depending on the stage — that is the behaviour the whole
phenology spine exists to enable, and a regression there would be silent.

Pure evaluation: compile the YAML, hand-build a context, walk the tree. No
database, so these live in the unit suite rather than alongside the
container-gated `integration/recommendations/test_mango_trees.py`.
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
from app.shared.conditions.context import SignalEntry

_SEEDS = Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"


def _tree(name: str) -> dict:
    return compile_tree(
        yaml.safe_load((_SEEDS / name).read_text(encoding="utf-8")), source_path=name
    )


def _ctx(*, stage: str | None, code: str, value: float | None) -> ConditionContext:
    """Context with one numeric petiole signal. ``value=None`` means no test
    has ever been ingested for the block."""
    signals = {}
    if value is not None:
        signals[code] = SignalEntry(time=datetime.now(UTC), value_numeric=Decimal(str(value)))
    return ConditionContext(
        block_id="b1",
        block_attributes={} if stage is None else {"growth_stage": stage},
        signals=signals,
    )


def _leaf(result: EvaluationResult) -> str:
    """Id of the leaf the walk ended on — lets a test distinguish two leaves
    that share an ``action_type`` (``leaf_no_data`` vs ``leaf_sufficient``)."""
    return result.path[-1].node_id


# ---------------------------------------------------------------------------
# Nitrogen — the stage-dependent one
# ---------------------------------------------------------------------------

_N = _tree("potato_petiole_nitrogen_v1.yaml")


def _n_ctx(stage: str | None, ppm: float | None) -> ConditionContext:
    return _ctx(stage=stage, code="petiole_no3n", value=ppm)


@pytest.mark.parametrize("stage", ["vegetative", "tuber_initiation"])
def test_nitrogen_deficient_below_early_band(stage: str) -> None:
    r = evaluate_tree(_N, _n_ctx(stage, 900))
    assert _leaf(r) == "leaf_deficient_early"
    assert r.outcome.action_type == "fertilize"
    assert r.outcome.severity == "warning"


@pytest.mark.parametrize("stage", ["vegetative", "tuber_initiation"])
def test_nitrogen_sufficient_inside_early_band(stage: str) -> None:
    r = evaluate_tree(_N, _n_ctx(stage, 1400))
    assert _leaf(r) == "leaf_sufficient"
    assert r.outcome.action_type == "no_action"


def test_nitrogen_deficient_below_bulking_band() -> None:
    r = evaluate_tree(_N, _n_ctx("tuber_bulking", 700))
    assert _leaf(r) == "leaf_deficient_bulking"
    assert r.outcome.action_type == "fertilize"


def test_same_reading_is_deficient_early_but_sufficient_at_bulking() -> None:
    """The whole point of stage gating: 900 ppm is a shortfall during
    tuberization (band 1200-1600) and perfectly adequate during bulking
    (band 800-1100). A single flat threshold cannot express this."""
    early = evaluate_tree(_N, _n_ctx("vegetative", 900))
    bulking = evaluate_tree(_N, _n_ctx("tuber_bulking", 900))

    assert early.outcome.action_type == "fertilize"
    assert bulking.outcome.action_type == "no_action"


def test_nitrogen_excess_at_maturation_warns_about_delayed_maturity() -> None:
    r = evaluate_tree(_N, _n_ctx("maturation", 1500))
    assert _leaf(r) == "leaf_excess_maturation"
    assert r.outcome.severity == "warning"
    # Never advise more nitrogen this late.
    assert r.outcome.action_type != "fertilize"


def test_nitrogen_low_at_maturation_is_informational_not_a_fertilize_call() -> None:
    r = evaluate_tree(_N, _n_ctx("maturation", 300))
    assert _leaf(r) == "leaf_low_maturation"
    assert r.outcome.severity == "info"
    assert r.outcome.action_type != "fertilize"


def test_nitrogen_inside_maturation_band_is_silent() -> None:
    r = evaluate_tree(_N, _n_ctx("maturation", 550))
    assert _leaf(r) == "leaf_sufficient"


def test_missing_reading_reports_no_data_not_sufficiency() -> None:
    """Regression guard for false reassurance. A missing signal resolves to
    None and every comparison short-circuits to False, which without the
    presence probe would walk to `leaf_sufficient` and tell the grower
    nitrogen is fine when nothing was ever measured."""
    r = evaluate_tree(_N, _n_ctx("tuber_bulking", None))
    assert _leaf(r) == "leaf_no_data"
    assert r.outcome.action_type == "no_action"


def test_nitrogen_silent_before_the_sampling_window() -> None:
    assert _leaf(evaluate_tree(_N, _n_ctx("emergence", 900))) == "leaf_out_of_window"


def test_nitrogen_silent_when_stage_is_unresolved() -> None:
    """Blocks whose stage has not been auto-advanced yet carry no
    growth_stage; the tree must fail closed rather than assume a band."""
    assert _leaf(evaluate_tree(_N, _n_ctx(None, 900))) == "leaf_out_of_window"


def test_nitrogen_threshold_is_tenant_overridable() -> None:
    ctx = _n_ctx("vegetative", 900)
    assert evaluate_tree(_N, ctx).outcome.action_type == "fertilize"
    # A cultivar with a lower requirement than Russet Burbank.
    loosened = evaluate_tree(_N, ctx, param_overrides={"sufficient_early": 800})
    assert loosened.outcome.action_type == "no_action"


# ---------------------------------------------------------------------------
# Phosphorus / potassium — single-band, window-gated
# ---------------------------------------------------------------------------

_P = _tree("potato_petiole_phosphorus_v1.yaml")
_K = _tree("potato_petiole_potassium_v1.yaml")


@pytest.mark.parametrize(
    ("tree", "code", "low", "ok"),
    [
        (_P, "petiole_p", 0.18, 0.30),
        (_K, "petiole_k", 7.0, 9.0),
    ],
    ids=["phosphorus", "potassium"],
)
def test_pk_deficiency_and_sufficiency(tree: dict, code: str, low: float, ok: float) -> None:
    deficient = evaluate_tree(tree, _ctx(stage="tuber_bulking", code=code, value=low))
    assert _leaf(deficient) == "leaf_deficient"
    assert deficient.outcome.action_type == "fertilize"

    sufficient = evaluate_tree(tree, _ctx(stage="tuber_bulking", code=code, value=ok))
    assert _leaf(sufficient) == "leaf_sufficient"


@pytest.mark.parametrize(
    ("tree", "code", "low"),
    [(_P, "petiole_p", 0.18), (_K, "petiole_k", 7.0)],
    ids=["phosphorus", "potassium"],
)
@pytest.mark.parametrize("stage", ["vegetative", "maturation"])
def test_pk_refuse_to_interpret_outside_the_published_window(
    tree: dict, code: str, low: float, stage: str
) -> None:
    """The published P and K bands are quoted at tuber bulking only. Outside
    that window the tree must stay silent rather than extrapolate a
    threshold the sources do not give."""
    r = evaluate_tree(tree, _ctx(stage=stage, code=code, value=low))
    assert _leaf(r) == "leaf_out_of_window"


@pytest.mark.parametrize(
    ("tree", "code"), [(_P, "petiole_p"), (_K, "petiole_k")], ids=["phosphorus", "potassium"]
)
def test_pk_missing_reading_reports_no_data(tree: dict, code: str) -> None:
    r = evaluate_tree(tree, _ctx(stage="tuber_bulking", code=code, value=None))
    assert _leaf(r) == "leaf_no_data"


# ---------------------------------------------------------------------------
# KB P1 contract — every new seed carries its provenance and 4-horizon actions
# ---------------------------------------------------------------------------

_ALL = pytest.mark.parametrize(
    "name",
    [
        "potato_petiole_nitrogen_v1.yaml",
        "potato_petiole_phosphorus_v1.yaml",
        "potato_petiole_potassium_v1.yaml",
    ],
)


@_ALL
def test_seed_carries_evidence_and_transferability(name: str) -> None:
    compiled = _tree(name)

    evidence = compiled["evidence"]
    assert evidence["confidence"] in ("very_high", "high", "medium", "low")
    assert evidence["citations"], "a scientific KB seed must cite its thresholds"
    assert evidence["notes"], "uncertainty must be stated explicitly, not omitted"

    assert set(compiled["transferability"]) >= {"egypt", "middle_east", "global"}


@_ALL
def test_actionable_leaves_carry_horizoned_actions(name: str) -> None:
    """A leaf that asks the grower to do something must say what to do now
    versus later — the 4-horizon contract from KB P1-B."""
    for node_id, node in _tree(name)["nodes"].items():
        outcome = node.get("outcome")
        if not outcome or outcome["action_type"] == "no_action":
            continue
        assert outcome.get("actions"), f"{node_id} is actionable but carries no actions block"
