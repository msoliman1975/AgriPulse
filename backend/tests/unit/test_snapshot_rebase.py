"""Rebasing a cloned timestamp, and the two values that must not move.

The clone shifts every timestamp by one offset so the simulated tenant looks
current. Valid-time columns break that rule: they use the extremes of the
datetime range as sentinels — ``grid_configs.effective_from`` is ``0001-01-01``
for "has always applied", and the matching upper bounds sit at the maximum for
"still applies". Shifting one says nothing, because "always" does not move when
the season does, and shifting the lower one raises OverflowError outright.

That is not hypothetical: the first real clone load against production died on
`grid_configs` with `OverflowError: date value out of range`, because the run's
offset happened to be negative.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.simulation.snapshot import _rebase

_FORWARD = timedelta(days=3, hours=7)
_BACKWARD = -timedelta(days=1, hours=15, minutes=18)


def test_an_ordinary_observation_moves_by_the_offset() -> None:
    observed = datetime(2026, 3, 5, 9, 30, tzinfo=UTC)
    assert _rebase(observed, _FORWARD) == observed + _FORWARD
    assert _rebase(observed, _BACKWARD) == observed + _BACKWARD


@pytest.mark.parametrize("offset", [_FORWARD, _BACKWARD])
def test_the_beginning_of_time_sentinel_stays_put(offset: timedelta) -> None:
    """`0001-01-01` means "has always applied" — a season shift cannot move it.

    With a negative offset this is also the case that used to crash: there is
    no datetime a day and a half before `datetime.min`.
    """
    sentinel = datetime(1, 1, 1, tzinfo=UTC)
    assert _rebase(sentinel, offset) == sentinel


@pytest.mark.parametrize("offset", [_FORWARD, _BACKWARD])
def test_the_end_of_time_sentinel_stays_put(offset: timedelta) -> None:
    """The mirror image: "still applies" must not become a real date."""
    sentinel = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert _rebase(sentinel, offset) == sentinel


def test_a_value_that_would_overflow_is_returned_unchanged() -> None:
    """Backstop for anything close enough to an extreme to overflow.

    Nothing describing a real observation lives within days of year 1, so a
    value that cannot survive the shift is a sentinel by construction. Losing
    the run to OverflowError helps nobody.
    """
    near_min = datetime.min.replace(tzinfo=UTC) + timedelta(hours=1)
    assert _rebase(near_min, _BACKWARD) == near_min

    near_max = datetime.max.replace(tzinfo=UTC) - timedelta(hours=1)
    assert _rebase(near_max, _FORWARD) == near_max
