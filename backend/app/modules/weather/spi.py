"""Standardized Precipitation Index — pure maths, no I/O.

SPI (McKee et al. 1993; WMO-1090 user guide) expresses an accumulated rainfall
total as the number of standard deviations it sits from the long-run normal for
that place and time of year. The transform is:

  1. accumulate precipitation over a window (30 / 90 / 180 days);
  2. fit a gamma distribution to the historical accumulations for the same
     window ending on the same calendar day;
  3. map the target accumulation through that fitted CDF, then back through the
     inverse standard-normal CDF.

Two implementation notes that are not incidental:

**Zero inflation.** Gamma is undefined at zero and rainfall records are full of
zeros, so the standard treatment is a mixed distribution
``H(x) = q + (1 - q)·G(x)`` where ``q`` is the observed probability of a dry
window. Fitting a bare gamma to a series containing zeros silently produces
nonsense, which is the classic way to ship a broken SPI.

**⚠️ SPI is weak in hyper-arid climates, which is where our farms are.** WMO's
own guidance is that SPI becomes unreliable where a large share of windows are
completely dry, because ``q`` dominates and the index collapses onto a handful
of discrete values. Egyptian orchards in the Nile Valley and Delta see on the
order of tens of millimetres a year, so many 90-day windows are exactly zero.
This module therefore returns ``None`` rather than a number whenever the fit
would be degenerate, and the caller emits no row: a gap in the series is honest
about that, a fabricated 0.0 ("perfectly normal conditions") is not.

No scipy — it is installed in some dev environments but is NOT a declared
dependency in pyproject.toml, so it does not exist in the container. The
regularised incomplete gamma below is the Numerical Recipes series/continued
-fraction pair on top of ``math.lgamma``; the inverse normal comes from
``statistics.NormalDist``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist

# WMO's own tables stop at ±3; beyond that the fitted tail is extrapolation
# from a handful of observations rather than measurement. Clamping keeps a
# freak value from rendering as a 12-sigma event on a chart axis.
SPI_CLAMP = 3.0

# Below this many historical windows the fit is not worth reporting. WMO
# recommends 30 years of record; we cannot require that of a platform whose
# archive starts in 1940 for some farms and last season for others, so this is
# a floor rather than a target — and `SpiResult.sample_size` carries the real
# number so a consumer can weigh it.
MIN_SAMPLES = 20

# If more than this share of historical windows are bone dry, the mixed
# distribution is mostly point mass at zero and SPI degenerates into a
# near-binary signal. See the hyper-arid note above.
MAX_DRY_FRACTION = 0.9

_MAX_ITER = 200
_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class SpiResult:
    """An SPI value plus the evidence behind it."""

    value: float
    sample_size: int
    dry_fraction: float
    shape: float
    scale: float


def _lower_regularized_gamma(a: float, x: float) -> float:
    """Regularised lower incomplete gamma: lower_gamma(a, x) / gamma(a)."""
    if x < 0 or a <= 0:
        raise ValueError(f"invalid arguments to P(a, x): a={a}, x={x}")
    if x == 0:
        return 0.0
    if x < a + 1.0:
        # Series representation — converges fast below the peak.
        term = 1.0 / a
        total = term
        n = a
        for _ in range(_MAX_ITER):
            n += 1.0
            term *= x / n
            total += term
            if abs(term) < abs(total) * _EPS:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))

    # Continued fraction for Q(a, x), then P = 1 - Q. Modified Lentz.
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, _MAX_ITER + 1):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return 1.0 - q


def fit_gamma(values: Sequence[float]) -> tuple[float, float] | None:
    """Shape/scale by Thom's (1966) MLE approximation, the SPI standard.

    ``values`` must be strictly positive — zeros are handled by the caller's
    mixed distribution, not here. Returns ``None`` when the sample cannot
    support a fit (too few points, or no spread at all, which would make the
    log-mean difference zero and the shape parameter infinite).
    """
    positives = [v for v in values if v > 0]
    if len(positives) < 2:
        return None
    mean = sum(positives) / len(positives)
    if mean <= 0:
        return None
    log_mean = sum(math.log(v) for v in positives) / len(positives)
    a = math.log(mean) - log_mean
    # a <= 0 means every value is identical — no distribution to fit.
    if a <= _EPS:
        return None
    shape = (1.0 + math.sqrt(1.0 + 4.0 * a / 3.0)) / (4.0 * a)
    if shape <= 0 or not math.isfinite(shape):
        return None
    scale = mean / shape
    if scale <= 0 or not math.isfinite(scale):
        return None
    return shape, scale


def compute_spi(
    target_accumulation: float,
    history: Sequence[float],
    *,
    min_samples: int = MIN_SAMPLES,
    max_dry_fraction: float = MAX_DRY_FRACTION,
) -> SpiResult | None:
    """SPI for one accumulation against its own historical distribution.

    ``history`` is the set of comparable accumulations — same window length,
    same calendar position, earlier years. Returns ``None`` whenever the result
    would be more artefact than measurement; every such case is a reason for
    the caller to emit no row rather than to substitute a value.
    """
    if target_accumulation < 0:
        raise ValueError(f"accumulation cannot be negative: {target_accumulation}")
    sample = [v for v in history if v is not None and v >= 0]
    if len(sample) < min_samples:
        return None

    dry = sum(1 for v in sample if v <= 0)
    dry_fraction = dry / len(sample)
    if dry_fraction > max_dry_fraction:
        # Mostly point mass at zero — see the hyper-arid note in the module
        # docstring. An SPI here would be a near-binary signal wearing the
        # clothes of a continuous one.
        return None

    fitted = fit_gamma(sample)
    if fitted is None:
        return None
    shape, scale = fitted

    if target_accumulation <= 0:
        # A dry window sits inside the zero point mass. Convention places it at
        # the midpoint of that mass rather than at its edge, so a dry spell in
        # a climate where dryness is common does not read as more extreme than
        # the record supports.
        cumulative = dry_fraction / 2.0
    else:
        gamma_cdf = _lower_regularized_gamma(shape, target_accumulation / scale)
        cumulative = dry_fraction + (1.0 - dry_fraction) * gamma_cdf

    # Guard the inverse-normal call: exactly 0 or 1 maps to infinity.
    cumulative = min(max(cumulative, _EPS), 1.0 - _EPS)
    value = NormalDist().inv_cdf(cumulative)
    value = max(-SPI_CLAMP, min(SPI_CLAMP, value))

    return SpiResult(
        value=round(value, 3),
        sample_size=len(sample),
        dry_fraction=round(dry_fraction, 3),
        shape=round(shape, 4),
        scale=round(scale, 4),
    )


# --- windowing --------------------------------------------------------------
#
# SPI compares like with like: an accumulation is only meaningful against the
# SAME window length ending at the SAME point in the calendar, in other years.
# Comparing a 90-day October total against a 90-day April total would measure
# the season, not the anomaly.

# Calendar tolerance when gathering prior years. A window ending on 12 Oct is
# comparable to one ending on 5-19 Oct; widening the net this much multiplies
# the sample size, which matters a great deal when the archive is short.
_DOY_TOLERANCE_DAYS = 7


def accumulate(precip_by_date: Mapping[date, float], end: date, window_days: int) -> float | None:
    """Total precipitation over the ``window_days`` ending inclusively on ``end``.

    Returns ``None`` if the window is not fully covered. A partial window would
    understate the total and so overstate the drought — the one direction of
    error that turns this index into a false alarm.
    """
    total = 0.0
    for offset in range(window_days):
        value = precip_by_date.get(end - timedelta(days=offset))
        if value is None:
            return None
        total += value
    return total


def comparable_history(
    precip_by_date: Mapping[date, float],
    target: date,
    window_days: int,
    *,
    doy_tolerance: int = _DOY_TOLERANCE_DAYS,
) -> list[float]:
    """Accumulations from earlier years ending near ``target``'s calendar day.

    Only strictly-earlier dates are used, so the value never contributes to its
    own distribution. Incomplete windows are dropped rather than zero-filled.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be >= 1, got {window_days}")
    out: list[float] = []
    earliest = min(precip_by_date) if precip_by_date else target

    year = target.year - 1
    while True:
        try:
            anchor = target.replace(year=year)
        except ValueError:
            # 29 February in a non-leap year — step to the 28th rather than
            # dropping the whole year.
            anchor = target.replace(year=year, day=28)
        if anchor - timedelta(days=window_days + doy_tolerance) < earliest:
            break
        for shift in range(-doy_tolerance, doy_tolerance + 1):
            end = anchor + timedelta(days=shift)
            if end >= target:
                continue
            total = accumulate(precip_by_date, end, window_days)
            if total is not None:
                out.append(total)
        year -= 1
    return out


__all__ = [
    "MAX_DRY_FRACTION",
    "MIN_SAMPLES",
    "SPI_CLAMP",
    "SpiResult",
    "accumulate",
    "comparable_history",
    "compute_spi",
    "fit_gamma",
]
