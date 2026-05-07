"""Per-(block, index, day-of-year) baseline computation.

Pure functions — no DB, no I/O — so the recompute task and unit tests
share the same code. The repository writes the resulting rows; the
service consults them at compute time to populate
``block_index_aggregates.baseline_deviation`` (a z-score).

Definitions:

  * **Baseline** for `(block, index, day-of-year d)` is the mean ±
    std of all historical aggregate rows whose observation date is
    within ``window_days`` of `d` on the calendar (year-agnostic).
  * **Deviation** for a fresh row at value `v` is
    ``(v - baseline_mean) / baseline_std`` — units of standard
    deviations. Negative → block is below historical norm for this
    time of year.

Implementation notes:

  * The rolling window wraps around year boundaries. A row observed on
    Jan 3 contributes to the baseline of any DOY in 1..10 (with
    ``window_days=7``). The wrap matters for crops with phenology
    that crosses December into January.
  * We require at least ``min_sample_count`` rows in the window
    (default 3) to emit a baseline — fewer than that and the std
    estimate is too noisy. Below the floor we skip the DOY, leaving
    consumers to fall back to None deviations on new blocks.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class HistoryRow:
    """One source row used to build the baselines.

    Carries enough context to bucket by day-of-year and count distinct
    years for ``years_observed``. Real callers pull these from
    ``block_index_aggregates`` filtered to (block_id, index_code).
    """

    time: datetime
    mean: Decimal


@dataclass(frozen=True, slots=True)
class BaselineRow:
    """One computed baseline ready to upsert."""

    day_of_year: int
    baseline_mean: Decimal
    baseline_std: Decimal
    sample_count: int
    years_observed: int


_DAYS_IN_YEAR = 366  # the inclusive DOY range we emit (1..366); cycle is 365


def _doy_distance(a: int, b: int) -> int:
    """Calendar distance between two day-of-year values, wrapping the year.

    DOY 1 (Jan 1) and DOY 365 (Dec 31, non-leap) are 1 day apart on the
    calendar, not 2 — we pin the cycle length to 365. The leap day
    (DOY 366 in leap years) is normalised to DOY 365 for cyclic
    arithmetic so it stays adjacent to DOY 1 the same way the calendar
    does.

    >>> _doy_distance(1, 365)
    1
    >>> _doy_distance(1, 366)
    1
    """
    cycle = 365
    a_norm = cycle if a == 366 else a
    b_norm = cycle if b == 366 else b
    raw = abs(a_norm - b_norm)
    return min(raw, cycle - raw)


def compute_block_baselines(
    history: Iterable[HistoryRow],
    *,
    window_days: int = 7,
    min_sample_count: int = 3,
) -> list[BaselineRow]:
    """Compute one BaselineRow per DOY that has at least ``min_sample_count``
    contributing observations within the rolling window.

    DOYs with fewer samples are skipped — a consumer reading the table
    sees no row and treats deviation as None.
    """
    if window_days < 0:
        raise ValueError(f"window_days must be >= 0, got {window_days}")

    # Bucket history once by exact DOY. We then sweep target DOYs and
    # union the buckets within the window.
    by_doy: dict[int, list[Decimal]] = {}
    by_doy_years: dict[int, set[int]] = {}
    for row in history:
        if row.mean is None:
            continue
        doy = row.time.timetuple().tm_yday
        by_doy.setdefault(doy, []).append(row.mean)
        by_doy_years.setdefault(doy, set()).add(row.time.year)

    out: list[BaselineRow] = []
    for target_doy in range(1, _DAYS_IN_YEAR + 1):
        values: list[Decimal] = []
        years: set[int] = set()
        for source_doy, source_values in by_doy.items():
            if _doy_distance(target_doy, source_doy) <= window_days:
                values.extend(source_values)
                years |= by_doy_years[source_doy]
        if len(values) < min_sample_count:
            continue
        floats = [float(v) for v in values]
        mean = Decimal(str(statistics.fmean(floats)))
        std = Decimal(str(statistics.pstdev(floats))) if len(floats) > 1 else Decimal(0)
        out.append(
            BaselineRow(
                day_of_year=target_doy,
                baseline_mean=mean.quantize(Decimal("0.0001")),
                baseline_std=std.quantize(Decimal("0.0001")),
                sample_count=len(values),
                years_observed=len(years),
            )
        )
    return out


def compute_baseline_deviation(
    *,
    value: Decimal,
    baseline_mean: Decimal,
    baseline_std: Decimal,
) -> Decimal | None:
    """Return ``(value - mean) / std`` quantised to 4 decimals.

    Returns None when std is zero (history has no variance — a flat
    baseline can't tell us anything about deviation magnitude).
    """
    if baseline_std == 0 or not math.isfinite(float(baseline_std)):
        return None
    delta = (value - baseline_mean) / baseline_std
    return delta.quantize(Decimal("0.0001"))


def find_baseline_for_doy(baselines: Sequence[BaselineRow], target_doy: int) -> BaselineRow | None:
    """Pick the BaselineRow exactly matching the target DOY, or None.

    The recompute job emits one row per DOY with at least the floor
    sample count, so this is a direct lookup, not a nearest-neighbour
    search. Day 366 in non-leap years simply isn't queried.
    """
    for row in baselines:
        if row.day_of_year == target_doy:
            return row
    return None
