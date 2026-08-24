"""Evaluate the size-aware mango trees built from the mango index guide.

`tatoo Docs/AgriPulse_Mango_Indices_Full_EN.xlsx` gives one expected index
band per tree size, and the whole point of these four trees is that the SAME
reading walks to a different leaf depending on the size recorded on the
block. A regression there is silent — the rule keeps firing, just against the
wrong band — so every tree gets a reading that is normal for one size and a
problem for another.

Three behaviours are pinned throughout:

* the size branch actually changes the verdict (not just the label);
* an unrecorded size reaches ``leaf_size_unknown`` and never guesses;
* a missing index reading fails closed rather than reading as zero.

Pure evaluation: compile the YAML, hand-build a context, walk the tree. No
database, so these live in the unit suite.
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

_SEEDS = Path(__file__).resolve().parents[3] / "app" / "modules" / "recommendations" / "seeds"


def _tree(name: str) -> dict[str, Any]:
    return compile_tree(
        yaml.safe_load((_SEEDS / name).read_text(encoding="utf-8")), source_path=name
    )


def _ctx(
    *,
    size: str | None = None,
    bearing: str | None = None,
    stage: str | None = None,
    **indices: float | None,
) -> ConditionContext:
    """Context carrying one crop-attribute size, an optional bearing status
    and stage, and whichever index means the caller names. An index passed as
    ``None`` is present-but-unmeasured, which is what a masked scene looks
    like; an index not passed at all is absent entirely."""
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
    """Every leaf in these trees declares an outcome; assert it so the type
    checker does not have to carry the None arm through every assertion."""
    assert result.outcome is not None
    return result.outcome


# ---------------------------------------------------------------------------
# Vigour — the index itself changes with the size, not only the threshold
# ---------------------------------------------------------------------------

_VIGOUR = _tree("mango_canopy_vigour_by_size_v1.yaml")


def test_vigour_small_reads_msavi_not_ndvi() -> None:
    """NDVI 0.18 is a catastrophe on a large tree and normal on a small one.
    The small branch must not look at NDVI at all."""
    r = evaluate_tree(_VIGOUR, _ctx(size="small", msavi=0.22, ndvi=0.18))
    assert _leaf(r) == "leaf_no_action"


def test_vigour_small_fires_below_msavi_floor() -> None:
    r = evaluate_tree(_VIGOUR, _ctx(size="small", msavi=0.11))
    assert _leaf(r) == "leaf_low_vigour"
    assert _outcome(r).action_type == "scout"
    assert _outcome(r).severity == "warning"


def test_vigour_medium_reads_savi() -> None:
    assert _leaf(evaluate_tree(_VIGOUR, _ctx(size="medium", savi=0.35))) == "leaf_no_action"
    assert _leaf(evaluate_tree(_VIGOUR, _ctx(size="medium", savi=0.20))) == "leaf_low_vigour"


def test_vigour_large_reads_ndvi() -> None:
    assert _leaf(evaluate_tree(_VIGOUR, _ctx(size="large", ndvi=0.72))) == "leaf_no_action"
    assert _leaf(evaluate_tree(_VIGOUR, _ctx(size="large", ndvi=0.50))) == "leaf_low_vigour"


def test_vigour_same_ndvi_opposite_verdicts_by_size() -> None:
    """The reading that proves the rule: NDVI 0.30 with a healthy small-tree
    MSAVI is fine on a small block and a warning on a large one."""
    small = evaluate_tree(_VIGOUR, _ctx(size="small", msavi=0.25, ndvi=0.30))
    large = evaluate_tree(_VIGOUR, _ctx(size="large", msavi=0.25, ndvi=0.30))
    assert _leaf(small) == "leaf_no_action"
    assert _leaf(large) == "leaf_low_vigour"


def test_vigour_unset_size_never_guesses() -> None:
    r = evaluate_tree(_VIGOUR, _ctx(msavi=0.01, savi=0.01, ndvi=0.01))
    assert _leaf(r) == "leaf_size_unknown"
    assert _outcome(r).action_type == "no_action"


def test_vigour_unmeasured_index_fails_closed() -> None:
    """A masked scene leaves `mean` None. That must not read as 0 and fire."""
    assert _leaf(evaluate_tree(_VIGOUR, _ctx(size="large", ndvi=None))) == "leaf_no_action"


# ---------------------------------------------------------------------------
# Moisture — the small-tree band is NEGATIVE, which is the whole point
# ---------------------------------------------------------------------------

_MOISTURE = _tree("mango_canopy_moisture_by_size_v1.yaml")


def test_moisture_negative_ndmi_is_normal_on_a_small_tree() -> None:
    """A small tree's pixel is mostly bare soil, so -0.10 is inside its band.
    A single 'NDMI below zero means thirsty' rule would alarm here."""
    assert _leaf(evaluate_tree(_MOISTURE, _ctx(size="small", ndmi=-0.10))) == "leaf_no_action"


def test_moisture_same_ndmi_fires_on_medium_and_large() -> None:
    assert _leaf(evaluate_tree(_MOISTURE, _ctx(size="medium", ndmi=-0.10))) == "leaf_dry"
    assert _leaf(evaluate_tree(_MOISTURE, _ctx(size="large", ndmi=-0.10))) == "leaf_dry"


def test_moisture_large_fires_while_still_positive() -> None:
    """0.05 is comfortably positive and still below the large-tree floor of
    0.11 — the case a zero-crossing rule would miss."""
    r = evaluate_tree(_MOISTURE, _ctx(size="large", ndmi=0.05))
    assert _leaf(r) == "leaf_dry"
    assert _outcome(r).action_type == "irrigate"


def test_moisture_reads_ndmi_not_ndwi() -> None:
    """The guide's 'NDWI' row is NDMI's formula. The platform's `ndwi` is
    McFeeters surface water — a different measurement. Supplying only `ndwi`
    must leave the rule with nothing to read."""
    assert _leaf(evaluate_tree(_MOISTURE, _ctx(size="large", ndwi=-0.9))) == "leaf_no_action"


def test_moisture_unset_size_never_guesses() -> None:
    assert _leaf(evaluate_tree(_MOISTURE, _ctx(ndmi=-0.9))) == "leaf_size_unknown"


# ---------------------------------------------------------------------------
# Cover gap — BSI runs the other way, so this fires on a ceiling
# ---------------------------------------------------------------------------

_GAP = _tree("mango_canopy_cover_gap_v1.yaml")


def test_gap_high_bsi_is_normal_on_a_small_tree() -> None:
    assert _leaf(evaluate_tree(_GAP, _ctx(size="small", bsi=0.45))) == "leaf_no_action"


def test_gap_same_bsi_fires_on_a_large_tree() -> None:
    r = evaluate_tree(_GAP, _ctx(size="large", bsi=0.45))
    assert _leaf(r) == "leaf_gap"
    assert _outcome(r).action_type == "scout"


def test_gap_fires_above_each_size_ceiling() -> None:
    assert _leaf(evaluate_tree(_GAP, _ctx(size="small", bsi=0.60))) == "leaf_gap"
    assert _leaf(evaluate_tree(_GAP, _ctx(size="medium", bsi=0.35))) == "leaf_gap"
    assert _leaf(evaluate_tree(_GAP, _ctx(size="large", bsi=0.20))) == "leaf_gap"


def test_gap_unset_size_never_guesses() -> None:
    assert _leaf(evaluate_tree(_GAP, _ctx(bsi=0.99))) == "leaf_size_unknown"


# ---------------------------------------------------------------------------
# NDRE — the rewrite. The old single 0.30 floor was wrong in both directions.
# ---------------------------------------------------------------------------

_NDRE = _tree("mango_post_harvest_nitrogen_v1.yaml")


def _ndre_ctx(size: str | None, value: float) -> ConditionContext:
    return _ctx(size=size, stage="post_harvest_flush", ndre=value)


def test_ndre_small_tree_no_longer_flagged_by_the_old_floor() -> None:
    """0.12 sits inside the small-tree band 0.08-0.18 and below the retired
    0.30 floor, so it used to open a deficiency card on every young orchard
    on every post-harvest scene."""
    assert _leaf(evaluate_tree(_NDRE, _ndre_ctx("small", 0.12))) == "leaf_no_action"


def test_ndre_large_tree_now_caught_by_the_old_floor_gap() -> None:
    """0.31 cleared the retired 0.30 floor while sitting well under the
    large-tree band 0.38-0.52 — a real loss of canopy nitrogen that used to
    pass silently."""
    r = evaluate_tree(_NDRE, _ndre_ctx("large", 0.31))
    assert _leaf(r) == "leaf_warn"
    assert _outcome(r).action_type == "other"


def test_ndre_fires_below_each_size_floor() -> None:
    assert _leaf(evaluate_tree(_NDRE, _ndre_ctx("small", 0.05))) == "leaf_warn"
    assert _leaf(evaluate_tree(_NDRE, _ndre_ctx("medium", 0.14))) == "leaf_warn"
    assert _leaf(evaluate_tree(_NDRE, _ndre_ctx("large", 0.20))) == "leaf_warn"


def test_ndre_stage_gate_still_holds_before_the_size_gate() -> None:
    ctx = _ctx(size="large", stage="flowering", ndre=0.05)
    assert _leaf(evaluate_tree(_NDRE, ctx)) == "leaf_no_action"


def test_ndre_unset_size_never_guesses() -> None:
    assert _leaf(evaluate_tree(_NDRE, _ndre_ctx(None, 0.01))) == "leaf_size_unknown"


# ---------------------------------------------------------------------------
# Catalogue-level invariants
# ---------------------------------------------------------------------------

_SIZE_AWARE = (
    "mango_canopy_vigour_by_size_v1.yaml",
    "mango_canopy_moisture_by_size_v1.yaml",
    "mango_canopy_cover_gap_v1.yaml",
    "mango_post_harvest_nitrogen_v1.yaml",
)


@pytest.mark.parametrize("name", _SIZE_AWARE)
def test_every_size_aware_tree_targets_egypt_and_mango(name: str) -> None:
    compiled = _tree(name)
    assert compiled["crop_paths"] == ["mango"]
    assert compiled["country_codes"] == ["EG"]


@pytest.mark.parametrize("name", _SIZE_AWARE)
def test_every_size_aware_tree_records_its_uncertainty(name: str) -> None:
    """The workbook states its own bands are unmeasured for these varieties.
    A tree that claims high confidence on them would be overselling."""
    evidence = _tree(name)["evidence"]
    assert evidence["confidence"] in {"medium", "low"}
    assert evidence["citations"]


@pytest.mark.parametrize("name", _SIZE_AWARE)
def test_every_threshold_is_a_tunable_parameter(name: str) -> None:
    """No bare numeric literal on the right of a comparison — a tenant must
    be able to move every band without editing the seed."""
    raw = yaml.safe_load((_SEEDS / name).read_text(encoding="utf-8"))
    literals: list[Any] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "op" in node and isinstance(node.get("right"), int | float):
                literals.append(node["right"])
            for child in node.values():
                _walk(child)
        elif isinstance(node, list):
            for child in node:
                _walk(child)

    _walk(raw["nodes"])
    assert literals == []
