"""Verdict logic for verification.

A verdict is the whole output of a verify, so getting one wrong is worse than
not verifying at all: a false `match` retires a real question, and a false
`drift` sends someone to re-run a year of imagery for nothing.

The tolerance is the load-bearing number here, and it is asserted from both
sides — tight enough that the known methodology change (pre-SCL-mask rows run
about 0.05 high) cannot hide under it, loose enough that Decimal quantisation
does not manufacture drift out of an exact recomputation.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.observer.verify import (
    MEAN_TOLERANCE,
    SceneVerification,
    _diff,
    _verdict_for,
    _worst,
)


class _Agg:
    """Minimal stand-in for `IndexAggregates` — only two fields are read."""

    def __init__(self, mean: Decimal | None, valid: int) -> None:
        self.mean = mean
        self.valid_pixel_count = valid


# ---- per-index verdicts ----------------------------------------------------


def test_an_exact_recomputation_matches() -> None:
    assert _verdict_for(Decimal("0.5123"), Decimal("0.5123"), 3214, 3214) == "match"


def test_quantisation_noise_below_the_tolerance_is_still_a_match() -> None:
    """Stored means are NUMERIC(7,4); the last digit rounds.

    If this produced drift, every verify would report drift and the signal
    would be worthless.
    """
    drifted = Decimal("0.5123") + (MEAN_TOLERANCE / 2)
    assert _verdict_for(Decimal("0.5123"), drifted, 3214, 3214) == "match"


def test_the_pre_mask_methodology_change_is_far_above_the_tolerance() -> None:
    """The worked example: rows averaged without SCL masking run ~0.05 high.

    This is the case the whole feature exists to catch, so it must not be
    anywhere near the noise floor.
    """
    assert _verdict_for(Decimal("0.6031"), Decimal("0.5488"), 3508, 3102) == "drift"
    assert abs(Decimal("0.6031") - Decimal("0.5488")) > MEAN_TOLERANCE * 100


def test_a_differing_pixel_count_is_drift_even_when_the_mean_agrees() -> None:
    """Same average over a different population is not the same answer.

    Two means can coincide while one was computed over 3,508 pixels and the
    other over 3,102 — the mask changed, and that is exactly the finding.
    """
    assert _verdict_for(Decimal("0.5123"), Decimal("0.5123"), 3508, 3102) == "drift"


def test_a_missing_recomputation_is_source_missing_not_drift() -> None:
    """ "The number is wrong" and "there is nothing to check it against" call
    for different actions, so they get different verdicts."""
    assert _verdict_for(Decimal("0.5"), None, 3214, None) == "source_missing"


def test_a_missing_stored_row_is_also_source_missing() -> None:
    assert _verdict_for(None, Decimal("0.5"), None, 3214) == "source_missing"


# ---- scene roll-up ---------------------------------------------------------


def test_one_drift_among_matches_makes_the_scene_drift() -> None:
    """Majority-voting here would let a real defect vanish behind its
    neighbours — six healthy indices do not excuse a seventh."""
    assert _worst(["match", "match", "match", "drift", "match"]) == "drift"


def test_an_error_outranks_a_drift() -> None:
    assert _worst(["drift", "error", "match"]) == "error"


def test_a_scene_with_nothing_to_compare_is_source_missing() -> None:
    assert _worst([]) == "source_missing"


def test_all_matching_is_a_match() -> None:
    assert _worst(["match", "match"]) == "match"


# ---- diff assembly ---------------------------------------------------------


def _stored(mean: str, valid: int) -> dict[str, dict[str, object]]:
    return {"ndvi": {"mean": Decimal(mean), "valid_pixel_count": valid}}


def test_diff_reports_signed_deltas_in_the_recomputed_direction() -> None:
    """The sign says which way the stored number is wrong.

    A negative delta means the stored value was too high — which is what a
    missing cloud mask produces, and knowing the direction is half the
    diagnosis.
    """
    result = _diff(
        recomputed={"ndvi": _Agg(Decimal("0.5488"), 3102)},
        stored=_stored("0.6031", 3508),
    )
    row = result.per_index["ndvi"]
    assert row["verdict"] == "drift"
    assert row["delta_mean"] == pytest.approx(-0.0543, abs=1e-6)
    assert row["delta_valid"] == -406


def test_diff_is_json_safe() -> None:
    """The result goes into a jsonb column; Decimal is not serialisable."""
    result = _diff(recomputed={"ndvi": _Agg(Decimal("0.5"), 10)}, stored=_stored("0.5", 10))
    for value in result.per_index["ndvi"].values():
        assert not isinstance(value, Decimal)


def test_an_index_present_only_in_the_store_is_reported_not_dropped() -> None:
    """A stored row whose raster has vanished is a finding.

    Silently omitting it would let a run report "all match" over a scene half
    of whose assets are gone.
    """
    result = _diff(recomputed={}, stored=_stored("0.5", 10))
    assert result.per_index["ndvi"]["verdict"] == "source_missing"
    assert result.verdict == "source_missing"


def test_an_index_present_only_in_the_raster_is_also_reported() -> None:
    result = _diff(recomputed={"ndvi": _Agg(Decimal("0.5"), 10)}, stored={})
    assert result.per_index["ndvi"]["verdict"] == "source_missing"


def test_diff_returns_a_scene_verification() -> None:
    result = _diff(recomputed={}, stored={})
    assert isinstance(result, SceneVerification)
    assert result.error is None
