"""Per-cell index features for ``scope: cell`` trees.

A cell walk used to see only the cell's own ``mean``; the z-score and trend
keys were the block's (see ``service._merge_cell_means``), so a cell tree
could not tell one cell's decline from the whole block's. This module turns a
block's cell history into six cell-grain keys the evaluator reads like any
other index field:

  * ``cell_z`` — the cell's latest mean against its own day-of-year
    baseline, in standard deviations (negative = below its norm). Same rules
    as the block baseline (``indices.baselines``: ±``window_days`` on the
    calendar, wrap-around, population SD, at least ``min_samples`` rows) with
    two differences: only rows from the latest scene's product count, so a
    sensor change is never read as a crop change, and the last
    ``exclude_recent_days`` are left out, so the scene being judged and the
    weeks just before it cannot pull the baseline toward themselves.
  * ``cell_baseline_samples`` — how many rows that baseline used (0 when
    none). Lets a tree say "no history yet" instead of failing silently.
  * ``cell_delta`` — latest mean minus the baseline mean, in index units.
    The effect size: a very even cell can reach a large z on a tiny change.
  * ``cell_trend`` — rising / falling / stable over the last
    ``trend_window_days``, from ``indices.trends.compute_trend``.
  * ``cell_spatial_z`` — the cell against the other cells of the same scene,
    ``(scene_mean - cell_mean) / SD`` (positive = below), with the same guards
    as ``grid.anomaly`` (at least ``min_cells`` cells, SD at least
    ``min_std``); None when a guard fails.
  * ``cell_valid_pct`` — clear-pixel share of the cell on the latest scene.

Pure functions only — no DB, no I/O — so the repository and the unit tests
share the same code.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.grid.anomaly import DEFAULT_MIN_CELLS, DEFAULT_MIN_STD
from app.modules.indices.trends import compute_trend

BASELINE_WINDOW_DAYS = 7
MIN_BASELINE_SAMPLES = 3
EXCLUDE_RECENT_DAYS = 60
TREND_WINDOW_DAYS = 30

CELL_FEATURE_KEYS: tuple[str, ...] = (
    "cell_z",
    "cell_baseline_samples",
    "cell_delta",
    "cell_trend",
    "cell_spatial_z",
    "cell_valid_pct",
)


@dataclass(frozen=True, slots=True)
class CellObservation:
    """One ``block_grid_aggregates`` row."""

    cell_id: UUID
    index_code: str
    product_id: UUID | None
    time: datetime
    mean: Decimal | None
    valid_pixel_pct: Decimal | None = None


def _doy_distance(a: datetime, b: datetime) -> int:
    """Calendar distance in days between two dates' day-of-year, wrapping
    the year (same cycle rule as ``indices.baselines._doy_distance``)."""
    cycle = 365
    da = min(a.timetuple().tm_yday, cycle)
    db = min(b.timetuple().tm_yday, cycle)
    raw = abs(da - db)
    return min(raw, cycle - raw)


def _q4(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def temporal_features(
    latest: CellObservation,
    history: Iterable[CellObservation],
    *,
    window_days: int = BASELINE_WINDOW_DAYS,
    min_samples: int = MIN_BASELINE_SAMPLES,
    exclude_recent_days: int = EXCLUDE_RECENT_DAYS,
    trend_window_days: int = TREND_WINDOW_DAYS,
) -> dict[str, Any]:
    """``cell_z`` / ``cell_baseline_samples`` / ``cell_delta`` / ``cell_trend``
    for one (cell, index) from that pair's history."""
    same_product = [h for h in history if h.product_id == latest.product_id and h.mean is not None]
    cutoff = latest.time - timedelta(days=exclude_recent_days)
    baseline = [
        float(h.mean)  # type: ignore[arg-type]
        for h in same_product
        if h.time < cutoff and _doy_distance(h.time, latest.time) <= window_days
    ]
    out: dict[str, Any] = {
        "cell_z": None,
        "cell_baseline_samples": len(baseline),
        "cell_delta": None,
    }
    if latest.mean is not None and len(baseline) >= min_samples:
        mu = statistics.fmean(baseline)
        sigma = statistics.pstdev(baseline)
        out["cell_delta"] = _q4(float(latest.mean) - mu)
        if sigma > 0:
            out["cell_z"] = _q4((float(latest.mean) - mu) / sigma)
    since = latest.time - timedelta(days=trend_window_days)
    out["cell_trend"] = compute_trend(
        [(h.time, h.mean) for h in same_product if since <= h.time <= latest.time]
    ).direction
    return out


def spatial_z(
    scene: dict[UUID, Decimal | None],
    *,
    min_cells: int = DEFAULT_MIN_CELLS,
    min_std: float = DEFAULT_MIN_STD,
) -> dict[UUID, Decimal]:
    """``cell_spatial_z`` for every cell of one scene. Empty when the scene
    has too few cells or is too uniform to say anything."""
    vals = {cid: float(v) for cid, v in scene.items() if v is not None}
    if len(vals) < min_cells:
        return {}
    mu = statistics.fmean(vals.values())
    sigma = statistics.pstdev(vals.values())
    if sigma < min_std:
        return {}
    return {cid: _q4((mu - v) / sigma) for cid, v in vals.items()}


def compute_cell_features(
    latest: Iterable[CellObservation],
    history: Iterable[CellObservation],
) -> dict[UUID, dict[str, dict[str, Any]]]:
    """``{cell_id: {index_code: {feature: value}}}`` for every latest row.

    ``history`` may include the latest rows themselves; the baseline's
    recent-days exclusion keeps them out of it, and the trend wants them in.
    """
    latest = list(latest)
    by_pair: dict[tuple[UUID, str], list[CellObservation]] = {}
    for h in history:
        by_pair.setdefault((h.cell_id, h.index_code), []).append(h)

    # A scene is (index, product, acquisition time): only cells observed on
    # the same pass are compared with each other.
    scenes: dict[tuple[str, UUID | None, datetime], dict[UUID, Decimal | None]] = {}
    for row in latest:
        scenes.setdefault((row.index_code, row.product_id, row.time), {})[row.cell_id] = row.mean
    spatial = {key: spatial_z(cells) for key, cells in scenes.items()}

    out: dict[UUID, dict[str, dict[str, Any]]] = {}
    for row in latest:
        feats = temporal_features(row, by_pair.get((row.cell_id, row.index_code), []))
        feats["cell_spatial_z"] = spatial[(row.index_code, row.product_id, row.time)].get(
            row.cell_id
        )
        feats["cell_valid_pct"] = row.valid_pixel_pct
        out.setdefault(row.cell_id, {})[row.index_code] = feats
    return out
