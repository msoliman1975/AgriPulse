"""Pure-function index trend computation (KB P2).

Turns a short time-series of per-block index means into three scalar
trend features the decision-tree evaluator can read as point-in-time
keys (``slope`` / ``delta`` / ``trend_direction``). This is the
"trends as data, not operators" stance: the evaluator stays pure and
point-in-time; the *direction of change* is precomputed here from the
recent aggregate history and exposed like any other index field.

No I/O — takes a list of ``(timestamp, value)`` points and returns a
``TrendResult``. The recommendations context-builder calls this once per
(block, index) while assembling the ConditionContext, so a condition can
say ``{source: indices, index_code: ndmi, key: trend_direction} == 'falling'``
or compare ``slope`` / ``delta`` numerically.

Direction uses an explicit dead-band (``DELTA_EPS``) so trivial scene-to-
scene noise reads as "stable" rather than flapping rising/falling. The
dead-band is a noise floor, not a crop-specific scientific threshold —
trees that need finer control can compare ``slope``/``delta`` directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

# Total change (last - first, in index units) below which the trend is
# called "stable". 0.02 is ~2% of a normalized index's -1..1 range — small
# enough to catch real moves, large enough to ignore single-scene jitter.
DELTA_EPS = Decimal("0.02")

# Minimum distinct points needed before a slope/direction is meaningful.
_MIN_POINTS = 2

RISING = "rising"
FALLING = "falling"
STABLE = "stable"


@dataclass(frozen=True, slots=True)
class TrendResult:
    """Scalar trend features for one (block, index) over a window.

    All ``None`` when there is too little history (< 2 valid points) —
    which the evaluator treats as a missing value (fail-closed), so a
    block with one observation never trips a trend rule.
    """

    slope: Decimal | None  # index units per day (least-squares fit)
    delta: Decimal | None  # last value - first value over the window
    direction: str | None  # "rising" | "falling" | "stable"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_trend(
    points: Sequence[tuple[datetime, Any]],
    *,
    delta_eps: Decimal = DELTA_EPS,
) -> TrendResult:
    """Compute (slope, delta, direction) from ``(time, value)`` points.

    Points may arrive in any order and may contain ``None`` values
    (cloud-masked scenes); they are filtered and sorted by time here.
    ``slope`` is the least-squares slope in *units per day*; ``delta`` is
    last - first across the retained window; ``direction`` is bucketed
    from ``delta`` against ``delta_eps``.
    """
    cleaned: list[tuple[datetime, float]] = []
    for ts, raw in points:
        val = _to_float(raw)
        if val is not None:
            cleaned.append((ts, val))

    if len(cleaned) < _MIN_POINTS:
        return TrendResult(slope=None, delta=None, direction=None)

    cleaned.sort(key=lambda p: p[0])
    t0 = cleaned[0][0]
    # x = days since the first retained observation.
    xs = [(ts - t0).total_seconds() / 86400.0 for ts, _ in cleaned]
    ys = [val for _, val in cleaned]

    delta_f = ys[-1] - ys[0]
    slope_f = _least_squares_slope(xs, ys)

    if delta_f > float(delta_eps):
        direction = RISING
    elif delta_f < -float(delta_eps):
        direction = FALLING
    else:
        direction = STABLE

    return TrendResult(
        slope=_q4(slope_f) if slope_f is not None else None,
        delta=_q4(delta_f),
        direction=direction,
    )


def _least_squares_slope(xs: list[float], ys: list[float]) -> float | None:
    """Least-squares slope of y over x. ``None`` if x has zero variance
    (every point on the same day) — delta still carries the change."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x == 0.0:
        return None
    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return cov_xy / var_x


def _q4(value: float) -> Decimal:
    """Quantize to NUMERIC(7,4)-style precision, matching index means."""
    return Decimal(repr(value)).quantize(Decimal("0.0001"))
