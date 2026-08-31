"""Evaluate `mango_canopy_health_v1` end-to-end against hand-built contexts.

The other mango seeds this file used to cover -- stress induction and
post-harvest nitrogen -- were retired by public migration 0079 and replaced by
`t_flower_induction_readiness` and `t_ndre_nitrogen`. All twenty-two `t_*`
trees are covered in `tests/unit/recommendations/test_mango_catalogue_trees.py`.

`mango_canopy_health_v1` stays because it asks a different question from any
of them: it judges the block against its OWN day-of-year history rather than
against the index guide's absolute band, so it catches a healthy block falling
where an absolute rule sees a block still inside its range.
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
from app.shared.conditions.context import IndicesEntry

pytestmark = [pytest.mark.integration]

_SEEDS = Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"


def _tree(name: str) -> dict:
    return compile_tree(
        yaml.safe_load((_SEEDS / name).read_text(encoding="utf-8")), source_path=name
    )


def _idx_dev(code: str, dev: float) -> dict[str, IndicesEntry]:
    return {
        code: IndicesEntry(time=datetime.now(UTC), mean=None, baseline_deviation=Decimal(str(dev)))
    }


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
