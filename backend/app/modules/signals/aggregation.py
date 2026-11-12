"""Pure-Python signals aggregation — reference + slow-path implementation.

The snapshot loader (snapshot.py) does the same work in SQL for the
hot per-evaluation path. This module exists for three reasons:

  1. **Test coverage.** SQL aggregation is hard to unit-test without a
     real Postgres + TimescaleDB. The pure-Python version is
     side-effect-free and trivial to cover with synthetic data.
  2. **Documentation.** When the SQL aggregation rules change, this
     module is the canonical reference the next reader can read end-to-
     end; the SQL CASE expression in snapshot.py points at this file.
  3. **Slow-path fallback.** If a future caller has the observations
     loaded in memory (e.g. backfill scripts, FE preview) it can use
     ``aggregate_observations`` directly instead of round-tripping to
     the DB for a one-off computation.

Behaviour MUST match the SQL in snapshot.py:

  * aggregation='count' (CS-14) works for EVERY value_kind: it counts
    the in-window observations themselves (mirrors SQL COUNT(*)), not
    their values, so it bypasses numeric value extraction.
  * Non-numeric value_kinds with any other rule resolve to the most
    recent observation's value, regardless of the configured rule.
  * Numeric value_kinds with aggregation='latest' resolve to the most
    recent value_numeric.
  * D6: on the latest path a window bounds how old the answer may be. An
    answer older than the window keeps its ``time`` but its values read as
    ``None`` (the SQL's ``stale`` flag). With no window, any age is valid.
  * ``days_since_latest`` is the whole days from the reported ``time`` to
    ``now`` (SQL: ``floor(epoch / 86400)``).
  * Numeric value_kinds with aggregation ∈ {mean, median, max, min, sum}
    (CS-14 adds sum) aggregate value_numeric over observations whose time
    falls inside [now - window_days, now], or all observations if
    window_days is None.
  * The reported ``time`` for an aggregated value is the max time
    across the observations that contributed (matches MAX(o.time) in
    the SQL).
  * If no observations pass the window filter, the signal is omitted
    from the result.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

Aggregation = Literal["latest", "mean", "median", "max", "min", "count", "sum"]
NUMERIC_VALUE_KINDS: frozenset[str] = frozenset({"numeric"})


@dataclass(frozen=True, slots=True)
class ObservationRow:
    """Minimal shape used by the aggregator. Subset of the
    signal_observations columns the snapshot loader cares about."""

    time: datetime
    value_numeric: Decimal | None = None
    value_categorical: str | None = None
    value_event: str | None = None
    value_boolean: bool | None = None


@dataclass(frozen=True, slots=True)
class AggregatedValue:
    """What the snapshot loader stores per signal in
    ``ConditionContext.signals``. Mirrors SignalEntry's value columns
    so callers can construct one trivially."""

    time: datetime
    value_numeric: Decimal | None = None
    value_categorical: str | None = None
    value_event: str | None = None
    value_boolean: bool | None = None
    days_since_latest: Decimal | None = None


def aggregate_observations(  # noqa: PLR0911  # one branch per aggregation rule reads clearer flat
    observations: Sequence[ObservationRow],
    *,
    value_kind: str,
    aggregation: Aggregation,
    window_days: int | None,
    now: datetime,
) -> AggregatedValue | None:
    """Collapse a list of observations into one ``AggregatedValue``.

    Returns ``None`` when nothing applies — empty input, or window
    excludes every row.
    """
    if not observations:
        return None

    # CS-14: `count` works for every value_kind — it counts the in-window
    # observations themselves, not their values, so it bypasses the numeric
    # value-extraction path below (mirrors SQL COUNT(*)).
    if aggregation == "count":
        rows = _in_window(observations, window_days=window_days, now=now)
        if not rows:
            return None
        latest_time = max(r.time for r in rows)
        return AggregatedValue(
            time=latest_time,
            value_numeric=Decimal(len(rows)),
            days_since_latest=_days_since(latest_time, now),
        )

    # Non-numeric kinds always use latest, regardless of aggregation
    # config — belt-and-brace against a misconfigured definition.
    if value_kind not in NUMERIC_VALUE_KINDS or aggregation == "latest":
        latest = max(observations, key=lambda o: o.time)
        if window_days is not None and latest.time < now - timedelta(days=window_days):
            return AggregatedValue(
                time=latest.time, days_since_latest=_days_since(latest.time, now)
            )
        return AggregatedValue(
            time=latest.time,
            days_since_latest=_days_since(latest.time, now),
            value_numeric=latest.value_numeric,
            value_categorical=latest.value_categorical,
            value_event=latest.value_event,
            value_boolean=latest.value_boolean,
        )

    # Numeric + non-latest aggregation. Apply window filter, then run
    # the rule on value_numeric only.
    rows = _in_window(observations, window_days=window_days, now=now)
    if not rows:
        return None
    values = [r.value_numeric for r in rows if r.value_numeric is not None]
    if not values:
        # Every in-window row has NULL value_numeric (shouldn't happen
        # under the value-presence CHECK constraint but defensive).
        return None
    aggregated_value = _apply_aggregate(values, aggregation)
    latest_time = max(r.time for r in rows)
    return AggregatedValue(
        time=latest_time,
        value_numeric=aggregated_value,
        days_since_latest=_days_since(latest_time, now),
    )


def _days_since(time: datetime, now: datetime) -> Decimal:
    return Decimal(math.floor((now - time).total_seconds() / 86400))


def _in_window(
    observations: Iterable[ObservationRow],
    *,
    window_days: int | None,
    now: datetime,
) -> list[ObservationRow]:
    if window_days is None:
        return list(observations)
    cutoff = now - timedelta(days=window_days)
    return [o for o in observations if o.time >= cutoff]


def _apply_aggregate(values: Sequence[Decimal], rule: Aggregation) -> Decimal:
    if rule == "mean":
        # Decimal-preserving mean; statistics.mean would coerce.
        return sum(values, Decimal(0)) / Decimal(len(values))
    if rule == "median":
        # statistics.median on Decimals returns Decimal for odd-len,
        # mean of middle two (also Decimal) for even-len.
        return Decimal(statistics.median(values))
    if rule == "max":
        return max(values)
    if rule == "min":
        return min(values)
    if rule == "sum":
        return sum(values, Decimal(0))
    if rule == "count":
        # Reachable only if a caller invokes _apply_aggregate directly;
        # aggregate_observations handles count before value extraction.
        return Decimal(len(values))
    raise ValueError(f"Unsupported aggregation rule for non-latest path: {rule!r}")
