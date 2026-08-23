"""Evaluate the held CWSI tree, which is written but not published.

`seeds/held/mango_irrigation_stress_cwsi_v1.yaml` sits outside the directory
`sync_from_disk` globs, because `cwsi` is pinned at its ceiling on prod (7225
of 7320 rows read exactly 1.0000). The rule itself is finished and reviewed —
only its input is untrustworthy — so it is exercised here rather than left to
rot until the CWSI bounds are calibrated. See the README beside the seed.

The interesting case is the bearing split: the same canopy temperature is
normal on a tree carrying fruit and a warning on one resting through an
alternate-bearing year, which is the whole reason `bearing_status` exists as
a field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.modules.recommendations.engine import EvaluationResult, TreeOutcome, evaluate_tree
from app.modules.recommendations.loader import compile_tree
from app.shared.conditions import ConditionContext
from app.shared.conditions.context import IndicesEntry

_HELD = (
    Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds" / "held"
)


def _tree(name: str) -> dict[str, Any]:
    return compile_tree(
        yaml.safe_load((_HELD / name).read_text(encoding="utf-8")), source_path=name
    )


def _ctx(
    *,
    size: str | None = None,
    bearing: str | None = None,
    stage: str | None = None,
    **indices: float | None,
) -> ConditionContext:
    attrs: dict[str, Any] = {}
    if size is not None:
        attrs["tree_size_class"] = size
    if bearing is not None:
        attrs["bearing_status"] = bearing
    return ConditionContext(
        block_id="b1",
        block_attributes={} if stage is None else {"growth_stage": stage},
        crop_attributes=attrs,
        indices={
            code: IndicesEntry(
                time=datetime.now(UTC),
                mean=None if value is None else Decimal(str(value)),
                baseline_deviation=None,
            )
            for code, value in indices.items()
        },
    )


def _leaf(result: EvaluationResult) -> str:
    return result.path[-1].node_id


def _outcome(result: EvaluationResult) -> TreeOutcome:
    assert result.outcome is not None
    return result.outcome


# ---------------------------------------------------------------------------
# CWSI — the bearing split, which is why `bearing_status` exists
# ---------------------------------------------------------------------------

_CWSI = _tree("mango_irrigation_stress_cwsi_v1.yaml")

_LOADED_STAGES = ("fruit_development", "post_harvest_flush")


@pytest.mark.parametrize("stage", _LOADED_STAGES)
def test_cwsi_bearing_tree_in_fruit_fill_tolerates_a_hot_canopy(stage: str) -> None:
    """0.40 is well over the resting large-tree ceiling of 0.25 and inside
    the bearing band. Judging a fruiting tree against the resting ceiling
    would alarm every productive block in Egypt, every summer."""
    ctx = _ctx(size="large", bearing="bearing", stage=stage, cwsi=0.40)
    assert _leaf(evaluate_tree(_CWSI, ctx)) == "leaf_no_action"


def test_cwsi_same_reading_fires_on_a_resting_tree() -> None:
    ctx = _ctx(size="large", bearing="not_bearing", stage="fruit_development", cwsi=0.40)
    r = evaluate_tree(_CWSI, ctx)
    assert _leaf(r) == "leaf_stress"
    assert _outcome(r).action_type == "irrigate"


def test_cwsi_bearing_tree_outside_fruit_fill_uses_the_tight_ceiling() -> None:
    """Bearing alone is not enough — the relaxation is tied to the fruit
    being on the tree, so flowering keeps the resting ceiling."""
    ctx = _ctx(size="large", bearing="bearing", stage="flowering", cwsi=0.40)
    assert _leaf(evaluate_tree(_CWSI, ctx)) == "leaf_stress"


def test_cwsi_bearing_tree_still_fires_above_the_relaxed_ceiling() -> None:
    ctx = _ctx(size="large", bearing="bearing", stage="fruit_development", cwsi=0.60)
    assert _leaf(evaluate_tree(_CWSI, ctx)) == "leaf_stress"


def test_cwsi_small_tree_tolerates_more_than_a_large_one() -> None:
    assert _leaf(evaluate_tree(_CWSI, _ctx(size="small", cwsi=0.32))) == "leaf_no_action"
    assert _leaf(evaluate_tree(_CWSI, _ctx(size="large", cwsi=0.32))) == "leaf_stress"


def test_cwsi_unrecorded_bearing_falls_to_the_tight_ceiling() -> None:
    """An absent bearing status must not buy the relaxed band — the safe
    default is to keep alarming."""
    ctx = _ctx(size="large", stage="fruit_development", cwsi=0.40)
    assert _leaf(evaluate_tree(_CWSI, ctx)) == "leaf_stress"


def test_cwsi_silent_without_the_thermal_product() -> None:
    """`cwsi` comes from Landsat. A farm with Sentinel-2 only has no entry at
    all, and the rule must reach no_action rather than error."""
    assert _leaf(evaluate_tree(_CWSI, _ctx(size="large", ndvi=0.7))) == "leaf_no_action"


def test_cwsi_unset_size_never_guesses() -> None:
    assert _leaf(evaluate_tree(_CWSI, _ctx(cwsi=0.99))) == "leaf_size_unknown"


def test_held_tree_is_not_in_the_published_seed_directory() -> None:
    """The whole reason this file exists. `sync_from_disk` globs
    `seeds/*.yaml` non-recursively, so a file here is never published — if
    somebody moves it up without calibrating CWSI, this fails."""
    published = _HELD.parent / "mango_irrigation_stress_cwsi_v1.yaml"
    assert not published.exists()


def test_held_tree_targets_egypt_and_mango_and_records_uncertainty() -> None:
    compiled = _tree("mango_irrigation_stress_cwsi_v1.yaml")
    assert compiled["crop_paths"] == ["mango"]
    assert compiled["country_codes"] == ["EG"]
    assert compiled["evidence"]["confidence"] in {"medium", "low"}
