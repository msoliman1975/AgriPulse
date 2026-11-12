"""Per-cell index features for ``scope: cell`` trees (Medjool tree 01).

``cell_features`` is pure, so every rule the canopy-diagnosis tree relies on
is pinned here without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.recommendations.cell_features import (
    CELL_FEATURE_KEYS,
    CellObservation,
    compute_cell_features,
    spatial_z,
    temporal_features,
)

S2 = uuid4()
NOW = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)


def _obs(mean, *, when=NOW, cell=None, product=S2, index="ndvi", valid=None):
    return CellObservation(
        cell_id=cell or UUID(int=1),
        index_code=index,
        product_id=product,
        time=when,
        mean=None if mean is None else Decimal(str(mean)),
        valid_pixel_pct=None if valid is None else Decimal(str(valid)),
    )


def _seasons(values, *, cell=None, product=S2):
    """One reading per earlier season on the same day of year."""
    return [
        _obs(v, when=NOW.replace(year=NOW.year - i - 1), cell=cell, product=product)
        for i, v in enumerate(values)
    ]


def test_cell_z_against_own_same_day_history() -> None:
    hist = _seasons([0.60, 0.62, 0.58])  # mean 0.60, pstdev ~0.0163
    out = temporal_features(_obs(0.55), hist)
    assert out["cell_baseline_samples"] == 3
    assert out["cell_delta"] == Decimal("-0.0500")
    assert out["cell_z"] < Decimal("-3")


def test_too_few_samples_leave_z_and_delta_empty() -> None:
    out = temporal_features(_obs(0.55), _seasons([0.60, 0.62]))
    assert out["cell_baseline_samples"] == 2
    assert out["cell_z"] is None
    assert out["cell_delta"] is None


def test_recent_rows_never_enter_the_baseline() -> None:
    recent = [_obs(0.10, when=NOW - timedelta(days=d)) for d in (5, 20, 59)]
    out = temporal_features(_obs(0.55), recent)
    assert out["cell_baseline_samples"] == 0


def test_rows_outside_the_day_of_year_window_are_ignored() -> None:
    far = [_obs(0.6, when=(NOW - timedelta(days=30)).replace(year=NOW.year - k)) for k in (1, 2, 3)]
    assert temporal_features(_obs(0.55), far)["cell_baseline_samples"] == 0


def test_other_product_rows_are_ignored() -> None:
    other = _seasons([0.6, 0.6, 0.6], product=uuid4())
    assert temporal_features(_obs(0.55), other)["cell_baseline_samples"] == 0


def test_flat_history_gives_delta_but_no_z() -> None:
    out = temporal_features(_obs(0.55), _seasons([0.6, 0.6, 0.6]))
    assert out["cell_delta"] == Decimal("-0.0500")
    assert out["cell_z"] is None


def test_spatial_z_positive_means_below_the_scene() -> None:
    cells = {UUID(int=i): Decimal("0.60") for i in range(1, 25)}
    weak = UUID(int=99)
    cells[weak] = Decimal("0.30")
    z = spatial_z(cells)
    assert z[weak] > Decimal("1.5")
    assert all(z[c] < 0 for c in cells if c != weak)


def test_spatial_z_needs_enough_cells_and_spread() -> None:
    few = {UUID(int=i): Decimal(str(0.5 + i / 100)) for i in range(5)}
    assert spatial_z(few) == {}
    even = {UUID(int=i): Decimal("0.5") for i in range(30)}
    assert spatial_z(even) == {}


def test_compute_cell_features_keys_and_scene_grouping() -> None:
    latest = [_obs(0.6, cell=UUID(int=i), valid=90) for i in range(1, 25)] + [
        _obs(0.3, cell=UUID(int=99), valid=40)
    ]
    history = _seasons([0.6, 0.61, 0.59], cell=UUID(int=99))
    out = compute_cell_features(latest, history)
    weak = out[UUID(int=99)]["ndvi"]
    assert set(weak) == set(CELL_FEATURE_KEYS)
    assert weak["cell_valid_pct"] == Decimal("40")
    assert weak["cell_spatial_z"] > Decimal("1.5")
    assert weak["cell_baseline_samples"] == 3
    # Cells without history still get every key, with no z.
    assert out[UUID(int=1)]["ndvi"]["cell_z"] is None
