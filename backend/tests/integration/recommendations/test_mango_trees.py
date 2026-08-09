"""Evaluate the seeded mango decision trees (PR-D2) end-to-end against
hand-built contexts. Compilation of every seed is covered in test_loader;
this asserts the agronomy logic walks to the right leaves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.modules.recommendations.engine import evaluate_tree
from app.modules.recommendations.loader import compile_tree
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import IndicesEntry, WeatherSnapshot

pytestmark = [pytest.mark.integration]

_SEEDS = Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"


def _tree(name: str) -> dict:
    return compile_tree(
        yaml.safe_load((_SEEDS / name).read_text(encoding="utf-8")), source_path=name
    )


def _idx(**means: float) -> dict[str, IndicesEntry]:
    return {
        code: IndicesEntry(time=datetime.now(UTC), mean=Decimal(str(v)), baseline_deviation=None)
        for code, v in means.items()
    }


def _idx_dev(code: str, dev: float) -> dict[str, IndicesEntry]:
    return {
        code: IndicesEntry(time=datetime.now(UTC), mean=None, baseline_deviation=Decimal(str(dev)))
    }


# ---- stress induction -----------------------------------------------------

_STRESS = _tree("mango_stress_induction_v1.yaml")


def _stress_ctx(*, stage: str, ndmi: float, tmin: float) -> ConditionContext:
    return ConditionContext(
        block_id="b1",
        block_attributes={"growth_stage": stage},
        indices=_idx(ndmi=ndmi),
        weather=WeatherSnapshot(forecast_72h={"air_temp_c_min": Decimal(str(tmin))}),
    )


def test_stress_induction_fires_when_wet_and_cool_in_preflowering() -> None:
    r = evaluate_tree(_STRESS, _stress_ctx(stage="pre_flowering", ndmi=0.45, tmin=12.0))
    assert r.outcome is not None
    assert r.outcome.action_type == "irrigate"
    assert r.outcome.severity == "warning"


def test_stress_induction_silent_when_warm() -> None:
    r = evaluate_tree(_STRESS, _stress_ctx(stage="pre_flowering", ndmi=0.45, tmin=22.0))
    assert r.outcome.action_type == "no_action"


def test_stress_induction_silent_when_dry() -> None:
    r = evaluate_tree(_STRESS, _stress_ctx(stage="pre_flowering", ndmi=0.10, tmin=12.0))
    assert r.outcome.action_type == "no_action"


def test_stress_induction_silent_outside_preflowering() -> None:
    r = evaluate_tree(_STRESS, _stress_ctx(stage="fruit_development", ndmi=0.45, tmin=12.0))
    assert r.outcome.action_type == "no_action"


# ---- post-harvest nitrogen (NDRE) -----------------------------------------

_NITRO = _tree("mango_post_harvest_nitrogen_v1.yaml")


def test_post_harvest_low_ndre_warns() -> None:
    ctx = ConditionContext(
        block_id="b1",
        block_attributes={"growth_stage": "post_harvest_flush"},
        indices=_idx(ndre=0.2),
    )
    r = evaluate_tree(_NITRO, ctx)
    assert r.outcome.action_type == "other"
    assert r.outcome.severity == "warning"


def test_post_harvest_healthy_ndre_silent() -> None:
    ctx = ConditionContext(
        block_id="b1",
        block_attributes={"growth_stage": "post_harvest_flush"},
        indices=_idx(ndre=0.5),
    )
    assert evaluate_tree(_NITRO, ctx).outcome.action_type == "no_action"


# ---- canopy health: SAVI on sandy soil, else NDVI -------------------------
#
# The tree used to open on a `canopy_size_class == small` node. Nothing ever
# set that column, so the node always fell through to the soil check — which
# is now the root.

_HEALTH = _tree("mango_canopy_health_v1.yaml")


def test_sandy_soil_uses_savi_branch() -> None:
    ctx = ConditionContext(
        block_id="b1",
        block_attributes={"soil_texture": "sandy"},
        indices=_idx_dev("savi", -2.0),
    )
    r = evaluate_tree(_HEALTH, ctx)
    assert r.outcome.action_type == "scout"
    assert [s.node_id for s in r.path] == ["soil_check", "savi_check", "leaf_scout"]


def test_clay_soil_uses_ndvi_branch() -> None:
    ctx = ConditionContext(
        block_id="b1",
        block_attributes={"soil_texture": "clay"},
        indices=_idx_dev("ndvi", -2.0),
    )
    r = evaluate_tree(_HEALTH, ctx)
    assert r.outcome.action_type == "scout"
    assert [s.node_id for s in r.path] == ["soil_check", "ndvi_check", "leaf_scout"]


def test_unknown_soil_uses_ndvi_branch() -> None:
    # No soil texture recorded -> the eq fails closed -> NDVI, same as clay.
    ctx = ConditionContext(
        block_id="b1",
        block_attributes={},
        indices=_idx_dev("ndvi", -2.0),
    )
    r = evaluate_tree(_HEALTH, ctx)
    assert [s.node_id for s in r.path] == ["soil_check", "ndvi_check", "leaf_scout"]


def test_healthy_ndvi_no_action() -> None:
    ctx = ConditionContext(
        block_id="b1",
        block_attributes={"soil_texture": "clay"},
        indices=_idx_dev("ndvi", -0.4),
    )
    assert evaluate_tree(_HEALTH, ctx).outcome.action_type == "no_action"
