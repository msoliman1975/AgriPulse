"""Unit tests for the read-only tree-explain path (Block Dock Conditions tab).

``explain_block`` is the read model behind the Farm Console's Conditions
tab: it re-walks every visible tree against a block's current signals and
reports *why* each one did or didn't fire, writing nothing.

These are DB-less — ``_prepare_block_evaluation`` is stubbed with a
hand-built ``_BlockEvaluation`` so the tests cover the part that has the
logic in it: status classification and step serialization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from app.modules.recommendations.errors import BlockNotInFarmError
from app.modules.recommendations.service import (
    RecommendationsServiceImpl,
    _BlockEvaluation,
    _explain_steps,
)
from app.shared.conditions import ConditionContext

_BLOCK_ID = UUID("00000000-0000-0000-0000-0000000000b1")
_T = datetime(2026, 6, 1, tzinfo=UTC)


def _tree(code: str, *, scope: str = "block", compiled: dict[str, Any] | None = None) -> dict:
    return {
        "tree_id": UUID(f"00000000-0000-0000-0000-{abs(hash(code)) % 10**12:012d}"),
        "tree_code": code,
        "name_en": code.replace("_", " ").title(),
        "name_ar": None,
        "version": 3,
        "scope": scope,
        "tree_compiled": compiled or _COMPILED_NDVI_FLOOR,
    }


# A two-node tree: NDVI below 0.45 → irrigate, otherwise no_action.
_COMPILED_NDVI_FLOOR: dict[str, Any] = {
    "root": "check_floor",
    "nodes": {
        "check_floor": {
            "label_en": "NDVI above fruit-set floor",
            "label_ar": None,
            "condition": {
                "tree": {
                    "op": "ge",
                    "left": {"source": "indices", "index_code": "ndvi", "key": "mean"},
                    "right": 0.45,
                }
            },
            "on_match": "leaf_clear",
            "on_miss": "leaf_irrigate",
        },
        "leaf_clear": {
            "label_en": "Vigour on target",
            "outcome": {"action_type": "no_action", "severity": "info", "confidence": 1.0},
        },
        "leaf_irrigate": {
            "label_en": "Vigour below floor",
            "outcome": {
                "action_type": "irrigate",
                "severity": "critical",
                "confidence": 0.94,
                "text_en": "Irrigate 30 mm within 24 hours.",
                "text_ar": None,
            },
        },
    },
}

_BROKEN_TREE: dict[str, Any] = {
    "root": "nowhere",  # points at a node that does not exist
    "nodes": {"other": {"outcome": {"action_type": "no_action"}}},
}


def _setup(
    *,
    ndvi_mean: float,
    block_trees: list[dict] | None = None,
    cell_trees: list[dict] | None = None,
    skipped_trees: list[dict] | None = None,
) -> _BlockEvaluation:
    latest = {"ndvi": {"time": _T, "mean": ndvi_mean, "baseline_deviation": -1.0}}
    ctx = ConditionContext.from_block_signals(
        block_id=str(_BLOCK_ID),
        crop_category="fruit",
        block_attributes={},
        latest_index_aggregates=latest,
    )
    return _BlockEvaluation(
        farm_id=_FARM_ID,
        block_crop_id=None,
        crop_path="citrus.valencia",
        crop_category="fruit",
        growth_stage="fruit_set",
        soil_texture=None,
        salinity_class=None,
        canopy_size_class=None,
        latest=latest,
        weather=None,
        weather_indices={},
        weather_risks={},
        signals={},
        grid={},
        ctx=ctx,
        block_trees=block_trees if block_trees is not None else [],
        cell_trees=cell_trees or [],
        skipped_trees=skipped_trees or [],
        param_overrides_per_tree={},
    )


def _service_with(setup: _BlockEvaluation | None) -> RecommendationsServiceImpl:
    """A service instance whose only wired-up behaviour is the stubbed setup."""
    svc = RecommendationsServiceImpl.__new__(RecommendationsServiceImpl)

    async def _prepare(**_kwargs: Any) -> _BlockEvaluation | None:
        return setup

    svc._prepare_block_evaluation = _prepare  # type: ignore[method-assign]
    return svc


_FARM_ID = UUID("00000000-0000-0000-0000-0000000000f1")


async def _explain(setup: _BlockEvaluation | None) -> dict[str, Any]:
    return await _service_with(setup).explain_block(
        block_id=_BLOCK_ID,
        tenant_id=UUID("00000000-0000-0000-0000-0000000000a1"),
        farm_id=_FARM_ID,
    )


@pytest.mark.asyncio
async def test_failing_condition_reports_fired_with_outcome() -> None:
    out = await _explain(_setup(ndvi_mean=0.39, block_trees=[_tree("irrigation_v3")]))
    (tree,) = out["trees"]
    assert tree["status"] == "fired"
    assert tree["action_type"] == "irrigate"
    assert tree["severity"] == "critical"
    assert tree["confidence"] == pytest.approx(0.94)
    assert tree["text_en"] == "Irrigate 30 mm within 24 hours."


@pytest.mark.asyncio
async def test_passing_condition_reports_clear_and_no_outcome() -> None:
    out = await _explain(_setup(ndvi_mean=0.63, block_trees=[_tree("irrigation_v3")]))
    (tree,) = out["trees"]
    # A no_action leaf leaves no recommendation row behind — the whole point
    # of this endpoint is that the console can still show it as evaluated.
    assert tree["status"] == "clear"
    assert tree["action_type"] is None
    assert tree["severity"] is None


@pytest.mark.asyncio
async def test_steps_carry_both_the_resolved_value_and_the_threshold() -> None:
    out = await _explain(_setup(ndvi_mean=0.39, block_trees=[_tree("irrigation_v3")]))
    steps = out["trees"][0]["steps"]
    decision = steps[0]
    assert decision["label_en"] == "NDVI above fruit-set floor"
    assert decision["matched"] is False
    # The resolved left-hand value...
    assert decision["values"]["indices.ndvi.mean"] == "0.39"
    # ...and the predicate it was compared against, so the UI can render
    # "0.39 · floor 0.45" rather than just "failed".
    assert decision["condition"]["op"] == "ge"
    assert decision["condition"]["right"] == 0.45


@pytest.mark.asyncio
async def test_leaf_step_has_no_condition() -> None:
    out = await _explain(_setup(ndvi_mean=0.39, block_trees=[_tree("irrigation_v3")]))
    leaf = out["trees"][0]["steps"][-1]
    assert leaf["node_id"] == "leaf_irrigate"
    assert leaf["matched"] is None
    assert leaf["condition"] is None


@pytest.mark.asyncio
async def test_cell_scoped_trees_are_listed_but_not_given_a_block_verdict() -> None:
    out = await _explain(
        _setup(ndvi_mean=0.39, cell_trees=[_tree("zone_anomaly_v2", scope="cell")])
    )
    (tree,) = out["trees"]
    # Evaluating a cell tree against block means would produce a verdict
    # that is simply wrong, so it is reported as per-cell with no steps.
    assert tree["status"] == "per_cell"
    assert tree["scope"] == "cell"
    assert tree["steps"] == []


@pytest.mark.asyncio
async def test_targeting_skips_are_reported_so_empty_blocks_can_explain_themselves() -> None:
    out = await _explain(_setup(ndvi_mean=0.39, skipped_trees=[_tree("mango_only_v1")]))
    (tree,) = out["trees"]
    assert tree["status"] == "skipped"
    assert tree["steps"] == []


@pytest.mark.asyncio
async def test_malformed_tree_reports_error_rather_than_failing_the_request() -> None:
    out = await _explain(
        _setup(ndvi_mean=0.39, block_trees=[_tree("broken_v1", compiled=_BROKEN_TREE)])
    )
    (tree,) = out["trees"]
    assert tree["status"] == "error"
    assert tree["error"] is not None


@pytest.mark.asyncio
async def test_block_with_no_farm_is_indistinguishable_from_not_yours() -> None:
    """A block with no parent farm cannot be authorized against one, so it
    404s exactly like a block belonging to someone else's farm — the caller
    learns nothing either way."""
    with pytest.raises(BlockNotInFarmError):
        await _explain(None)


@pytest.mark.asyncio
async def test_a_block_from_another_farm_is_refused() -> None:
    """Authorization happens against the farm_id query param, so the block
    must be verified to belong to it. Otherwise a user scoped to farm A
    could authorize with farm A and read a block from farm B."""
    setup = _setup(ndvi_mean=0.39, block_trees=[_tree("irrigation_v3")])
    svc = _service_with(setup)  # setup.farm_id is _FARM_ID
    with pytest.raises(BlockNotInFarmError):
        await svc.explain_block(
            block_id=_BLOCK_ID,
            tenant_id=UUID("00000000-0000-0000-0000-0000000000a1"),
            farm_id=UUID("00000000-0000-0000-0000-0000000000f9"),  # a different farm
        )


def test_explain_steps_tolerates_a_node_missing_from_compiled() -> None:
    """The walk records node ids; a compiled blob that lost one must not blow up."""

    class _Result:
        error = None
        path = [
            type(
                "S",
                (),
                {
                    "node_id": "ghost",
                    "matched": True,
                    "label_en": "gone",
                    "label_ar": None,
                    "condition_snapshot": {"indices.ndvi.mean": "0.5"},
                },
            )()
        ]

    steps = _explain_steps({"tree_compiled": {"nodes": {}}}, _Result())  # type: ignore[arg-type]
    assert steps[0]["condition"] is None
    assert steps[0]["values"] == {"indices.ndvi.mean": "0.5"}
