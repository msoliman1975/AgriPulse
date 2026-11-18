"""A cell with no card is not always healthy.

A condition that reads a value the block does not have counts as not met (the
engine will not fire on missing data), so a walk over a block with no data
often registers nothing and its cell reads exactly like a healthy one. The dry
run now lists the block data the walk read and found empty, so the panel can
say "no card, but data was missing".
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.recommendations.folding_authoring import _missing_inputs


def _walk(*snapshots: dict | None) -> SimpleNamespace:
    return SimpleNamespace(path=[SimpleNamespace(condition_snapshot=s) for s in snapshots])


def test_lists_block_data_that_read_empty_once_each_sorted() -> None:
    walk = _walk(
        {"indices.ndvi.baseline_deviation": None, "block.soil_texture": "loam"},
        None,
        {"signals.trap_catch.value": None, "indices.ndvi.baseline_deviation": None},
    )
    assert _missing_inputs(walk) == ["indices.ndvi.baseline_deviation", "signals.trap_catch.value"]


def test_tree_state_is_not_block_data() -> None:
    walk = _walk({"params.threshold": None, "vars.stage": None, "findings.dry.present": None})
    assert _missing_inputs(walk) == []


def test_a_walk_that_read_everything_has_nothing_missing() -> None:
    walk = _walk({"indices.ndvi.mean": "0.61", "findings.dry.present": False}, {})
    assert _missing_inputs(walk) == []
