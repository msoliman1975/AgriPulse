"""Unit tests for the grid spatial-anomaly detector."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from app.modules.grid.anomaly import (
    DEFAULT_K,
    CellMean,
    detect_low_outliers,
    effective_k,
)


def _cells(values: list[float]) -> list[CellMean]:
    return [
        CellMean(
            cell_id=uuid4(),
            row_idx=i // 10,
            col_idx=i % 10,
            mean=Decimal(str(v)),
            centroid_lon=0.0,
            centroid_lat=0.0,
        )
        for i, v in enumerate(values)
    ]


def test_returns_none_below_min_cells() -> None:
    # 5 cells, far below the 20 floor.
    assert detect_low_outliers(_cells([0.1, 0.8, 0.8, 0.8, 0.8])) is None


def test_returns_none_for_uniform_field() -> None:
    # 30 nearly-identical cells: spread under min_std, no spatial signal.
    cells = _cells([0.60 + (i % 2) * 0.001 for i in range(30)])
    assert detect_low_outliers(cells) is None


def test_flags_low_outlier_cells_worst_first() -> None:
    # 39 healthy cells around 0.7 + 1 clearly-low cell at 0.2.
    values = [0.70 + (i % 3) * 0.01 for i in range(39)] + [0.20]
    result = detect_low_outliers(_cells(values))
    assert result is not None
    assert len(result.flagged) >= 1
    # Worst (lowest mean) first.
    assert result.flagged[0].mean == 0.20
    assert result.flagged[0].z > 0  # below the mean
    means = [f.mean for f in result.flagged]
    assert means == sorted(means)


def test_returns_none_when_no_cell_crosses_threshold() -> None:
    # Bimodal but with real spread (std=0.05 > min_std): mean 0.65,
    # threshold 0.65 - 1.5*0.05 = 0.575, lowest cell 0.60 -- above it, so
    # nothing is flagged even though the field isn't uniform.
    values = [0.60] * 20 + [0.70] * 20
    assert detect_low_outliers(_cells(values)) is None


def test_k_threshold_changes_flagged_count() -> None:
    # Same field: mean 0.65, std 0.05. The 0.60 cohort sits 1.0 SD below.
    # At the default k=1.5 nothing is flagged; loosen to k=0.5 and the
    # whole low cohort crosses the threshold. Locks the G-3 contract that
    # a smaller k = more sensitive detection.
    values = [0.60] * 20 + [0.70] * 20
    assert detect_low_outliers(_cells(values), k=DEFAULT_K) is None
    loosened = detect_low_outliers(_cells(values), k=0.5)
    assert loosened is not None
    assert len(loosened.flagged) == 20
    assert all(f.mean == 0.60 for f in loosened.flagged)


def test_effective_k_prefers_block_override() -> None:
    # Per-block override wins over the tenant default...
    assert effective_k(block_override=Decimal("2.5"), tenant_default=1.5) == 2.5
    # ...and a NULL override falls through to the tenant/platform default.
    assert effective_k(block_override=None, tenant_default=1.5) == 1.5
    # Decimal overrides are coerced to float for the detector.
    assert isinstance(effective_k(block_override=Decimal("1.50"), tenant_default=1.5), float)


def test_severity_critical_when_many_flagged() -> None:
    # 30 healthy + 10 very low → >=10% flagged → critical.
    values = [0.75 for _ in range(30)] + [0.10 for _ in range(10)]
    result = detect_low_outliers(_cells(values))
    assert result is not None
    assert result.severity == "critical"
