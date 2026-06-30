"""Unit tests for the per-cell evaluation context builder (per-cell PR-C3).

Pure-fn tests of ``_merge_cell_means`` — the cell's ``indices`` context is the
block's latest aggregates with the cell's own ``mean`` swapped in (input
fidelity: cell imagery, inherit the rest). DB-less.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.recommendations.service import _merge_cell_means

_T = datetime(2026, 6, 1, tzinfo=UTC)


def test_cell_mean_overrides_block_mean_baseline_inherited() -> None:
    block = {"ndvi": {"time": _T, "mean": 0.60, "baseline_deviation": -1.2}}
    cell = {"ndvi": {"time": _T, "mean": 0.32}}
    out = _merge_cell_means(block, cell)
    # Cell's own mean wins; the block's baseline_deviation is inherited.
    assert out["ndvi"]["mean"] == 0.32
    assert out["ndvi"]["baseline_deviation"] == -1.2


def test_block_index_without_cell_data_is_unchanged() -> None:
    block = {"ndmi": {"time": _T, "mean": 0.4, "baseline_deviation": 0.1}}
    out = _merge_cell_means(block, {})  # cell has no observations
    assert out["ndmi"] == {"time": _T, "mean": 0.4, "baseline_deviation": 0.1}


def test_cell_index_absent_from_block_is_added_with_null_baseline() -> None:
    out = _merge_cell_means({}, {"evi": {"time": _T, "mean": 0.5}})
    assert out["evi"]["mean"] == 0.5
    assert out["evi"]["baseline_deviation"] is None


def test_does_not_mutate_inputs() -> None:
    block = {"ndvi": {"time": _T, "mean": 0.6, "baseline_deviation": -1.0}}
    _merge_cell_means(block, {"ndvi": {"time": _T, "mean": 0.2}})
    assert block["ndvi"]["mean"] == 0.6  # original untouched
