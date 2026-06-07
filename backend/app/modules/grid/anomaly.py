"""Spatial-anomaly detection over a block's sub-block grid.

The grid's reason for existing is to pin the *location* of trouble inside
a block. This module turns one scene's worth of per-cell index means into
a verdict: are there cells doing markedly worse than the rest of the
field right now?

We deliberately use a **spatial** (within-block, within-scene) outlier
test rather than an absolute floor or a temporal baseline:

  * Absolute floors are crop/season-dependent and noisy.
  * Temporal baselines need per-cell history we may not have yet.

A within-scene z-score against the block's own cell distribution is
self-normalising — it answers "which patches are worse than their
neighbours today?", which is exactly the scout-dispatch question. No
baseline, no per-crop tuning required for V1.

Pure functions only — no DB, no I/O — so the thresholds are trivial to
unit-test and the same logic can later back an on-demand API endpoint.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

# V1 defaults. Tunable per-tenant later; kept as module constants so the
# detector has no hidden config and the tests pin exact behaviour.
DEFAULT_K = 1.5  # std-devs below the block mean to flag a cell
DEFAULT_MIN_CELLS = 20  # need enough cells for the distribution to mean anything
DEFAULT_MIN_STD = 0.02  # below this the field is ~uniform: no spatial signal
# Escalation thresholds: critical if a large share is flagged OR the worst
# cell is extremely far below the field.
CRITICAL_FLAGGED_FRACTION = 0.10
CRITICAL_WORST_Z = 3.0


@dataclass(frozen=True, slots=True)
class CellMean:
    """One cell's index mean at a single scene."""

    cell_id: UUID
    row_idx: int
    col_idx: int
    mean: Decimal


@dataclass(frozen=True, slots=True)
class FlaggedCell:
    cell_id: UUID
    row_idx: int
    col_idx: int
    mean: float
    z: float  # std-devs below the block mean (positive = below)


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    block_mean: float
    block_std: float
    cells_considered: int
    flagged: tuple[FlaggedCell, ...]  # worst (lowest mean) first
    severity: str  # "warning" | "critical"


def detect_low_outliers(
    cells: list[CellMean],
    *,
    k: float = DEFAULT_K,
    min_cells: int = DEFAULT_MIN_CELLS,
    min_std: float = DEFAULT_MIN_STD,
) -> AnomalyResult | None:
    """Flag cells whose mean is ``k`` std-devs below the block's own mean.

    Returns ``None`` (no alert) when:
      * there are fewer than ``min_cells`` observed cells,
      * the cell-mean spread is below ``min_std`` (uniform field), or
      * no cell falls below the threshold.

    Otherwise returns an :class:`AnomalyResult` with the flagged cells
    sorted worst-first and a severity derived from how many cells are
    affected and how far the worst one sits below the field.
    """
    if len(cells) < min_cells:
        return None

    values = [float(c.mean) for c in cells]
    mu = statistics.fmean(values)
    sigma = statistics.pstdev(values)
    if sigma < min_std:
        return None

    threshold = mu - k * sigma
    flagged = [
        FlaggedCell(
            cell_id=c.cell_id,
            row_idx=c.row_idx,
            col_idx=c.col_idx,
            mean=float(c.mean),
            z=(mu - float(c.mean)) / sigma,
        )
        for c in cells
        if float(c.mean) < threshold
    ]
    if not flagged:
        return None

    flagged.sort(key=lambda f: f.mean)
    fraction = len(flagged) / len(cells)
    worst_z = flagged[0].z
    severity = (
        "critical"
        if fraction >= CRITICAL_FLAGGED_FRACTION or worst_z >= CRITICAL_WORST_Z
        else "warning"
    )
    return AnomalyResult(
        block_mean=mu,
        block_std=sigma,
        cells_considered=len(cells),
        flagged=tuple(flagged),
        severity=severity,
    )
