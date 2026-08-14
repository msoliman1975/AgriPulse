"""Pure time-interpolation over weather samples.

No I/O — takes `(time, value)` pairs and returns a scalar, so the unit
tests can pass hand-built fixtures and assert exact numbers.

Lives here rather than in `indices.computation` because it is weather
maths, not index maths: the fact that its first consumer is CWSI does
not make interpolating an hourly feed an indices concern. The import
contract agrees — `imagery` may not reach into `weather.repository`, so
the read and the interpolation both sit behind `WeatherService`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


def interpolate_air_temp_c(
    samples: Sequence[tuple[datetime, float | None]],
    at: datetime,
) -> float | None:
    """Linearly interpolate hourly air temperature to a given moment.

    The feed is hourly and Landsat crosses at ~08:17-08:24 UTC, so the
    reading CWSI needs almost never lands on a sample. Returns None when
    there is nothing usable to interpolate between — the caller then
    omits CWSI rather than inventing a value.

    Exact hits and out-of-range times both resolve to the nearest usable
    sample when one bracket is missing, so a scene at the very edge of
    the fetched window still gets a value rather than silently losing
    CWSI.
    """
    usable = sorted(
        ((time, float(value)) for time, value in samples if value is not None),
        key=lambda pair: pair[0],
    )
    if not usable:
        return None

    before: tuple[datetime, float] | None = None
    after: tuple[datetime, float] | None = None
    for sample in usable:
        if sample[0] <= at:
            before = sample
        else:
            after = sample
            break

    if before is None:
        return after[1] if after is not None else None
    if after is None:
        return before[1]
    if before[0] == at:
        return before[1]

    span = (after[0] - before[0]).total_seconds()
    if span <= 0:
        return before[1]
    weight = (at - before[0]).total_seconds() / span
    return before[1] + weight * (after[1] - before[1])
