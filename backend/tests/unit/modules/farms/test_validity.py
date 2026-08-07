"""Unit tests for crop-assignment valid time (pure, no DB).

The half-open rule is the whole thing. `[from, to)` is what lets one
assignment end and the next start on the same date without overlapping, and an
off-by-one in a single place is how the map, the reports and a decision tree
come to disagree about which crop is planted on a block.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest

from app.modules.farms.validity import (
    current_assignment,
    find_conflict,
    is_active_on,
    open_assignment_to_close,
    overlaps,
    state_on,
)

D = date


@dataclass
class A:
    """Stand-in for the ORM row — the helpers are duck-typed."""

    effective_from: date
    effective_to: date | None = None
    crop_path: str = "mango"
    id: UUID = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.id is None:
            self.id = uuid4()


# ---- half-open containment -------------------------------------------------


def test_range_contains_its_start_but_not_its_end() -> None:
    a = A(D(2026, 1, 1), D(2026, 4, 1))
    assert is_active_on(a, D(2026, 1, 1)) is True
    assert is_active_on(a, D(2026, 3, 31)) is True
    # The last day under the crop is 31 Mar; 1 Apr belongs to whatever starts
    # next. Inclusive `to` here would make the handover day overlap.
    assert is_active_on(a, D(2026, 4, 1)) is False


def test_before_the_start_is_not_active() -> None:
    assert is_active_on(A(D(2026, 11, 1), None), D(2026, 8, 6)) is False


def test_open_ended_never_ends() -> None:
    a = A(D(2019, 3, 4), None)
    assert is_active_on(a, D(2026, 8, 6)) is True
    assert is_active_on(a, D(2099, 1, 1)) is True


# ---- picking the current one ----------------------------------------------


def test_current_is_the_range_containing_today_not_the_latest_row() -> None:
    """The bug this replaces: a finished assignment stayed 'current' because
    nothing re-evaluated the stored flag as time passed."""
    finished = A(D(2025, 11, 1), D(2026, 3, 10), "tomato")
    ongoing = A(D(2026, 3, 10), None, "potato.spunta")
    assert current_assignment([finished, ongoing], D(2026, 8, 6)) is ongoing
    # ...and in March, before the handover, it was the tomato.
    assert current_assignment([finished, ongoing], D(2026, 3, 9)) is finished


def test_no_current_when_the_last_assignment_has_ended() -> None:
    ended = A(D(2025, 11, 1), D(2026, 3, 10))
    assert current_assignment([ended], D(2026, 8, 6)) is None


def test_a_future_assignment_is_not_current() -> None:
    """Planning next season ahead must not change what the map shows today."""
    future = A(D(2026, 11, 15), D(2027, 4, 30), "wheat")
    assert current_assignment([future], D(2026, 8, 6)) is None
    assert state_on(future, D(2026, 8, 6)) == "scheduled"


def test_state_labels() -> None:
    on = D(2026, 8, 6)
    assert state_on(A(D(2019, 3, 4), None), on) == "current"
    assert state_on(A(D(2024, 1, 1), D(2024, 6, 1)), on) == "past"
    assert state_on(A(D(2026, 11, 1), None), on) == "scheduled"


# ---- overlap ---------------------------------------------------------------


def test_touching_ranges_do_not_overlap() -> None:
    # One ends exactly where the next begins — the normal handover.
    assert overlaps(D(2026, 1, 1), D(2026, 3, 1), D(2026, 3, 1), None) is False


def test_one_day_of_shared_time_does_overlap() -> None:
    assert overlaps(D(2026, 1, 1), D(2026, 3, 2), D(2026, 3, 1), None) is True


def test_two_open_ended_ranges_always_overlap() -> None:
    """Which is why assigning must auto-close the previous open assignment."""
    assert overlaps(D(2019, 1, 1), None, D(2026, 1, 1), None) is True


def test_a_range_fully_inside_another_overlaps() -> None:
    assert overlaps(D(2026, 1, 1), D(2026, 12, 1), D(2026, 3, 1), D(2026, 4, 1)) is True


# ---- conflict detection ----------------------------------------------------


def test_conflict_names_the_colliding_assignment() -> None:
    existing = [A(D(2017, 11, 12), D(2018, 3, 20), "potato.diamant")]
    clash = find_conflict(existing, new_from=D(2018, 1, 1), new_to=D(2018, 2, 1))
    assert clash is not None
    assert clash.crop_path == "potato.diamant"


def test_the_assignment_being_auto_closed_is_not_a_conflict() -> None:
    """It ends exactly where the new one starts, so it is adjacent."""
    open_one = A(D(2019, 3, 4), None, "mango")
    clash = find_conflict([open_one], new_from=D(2026, 8, 6), new_to=None, closing_id=open_one.id)
    assert clash is None
    # Without the exemption it *would* conflict — two open ranges always do.
    assert find_conflict([open_one], new_from=D(2026, 8, 6), new_to=None) is open_one


def test_editing_an_assignment_ignores_itself() -> None:
    a = A(D(2026, 1, 1), D(2026, 6, 1))
    assert find_conflict([a], new_from=D(2026, 1, 1), new_to=D(2026, 7, 1), exclude_id=a.id) is None


# ---- auto-close selection --------------------------------------------------


def test_auto_close_picks_the_open_assignment() -> None:
    ended = A(D(2018, 11, 5), D(2019, 3, 4), "potato.spunta")
    ongoing = A(D(2019, 3, 4), None, "mango")
    assert open_assignment_to_close([ended, ongoing], D(2026, 8, 6)) is ongoing


def test_auto_close_never_touches_a_bounded_assignment() -> None:
    """A user who set an end date meant it; rewriting it would be silent data
    loss dressed up as convenience."""
    bounded = A(D(2025, 11, 1), D(2026, 3, 10), "tomato")
    assert open_assignment_to_close([bounded], D(2026, 8, 6)) is None


def test_auto_close_ignores_an_open_assignment_that_starts_later() -> None:
    """Backdating a new assignment must not close something that begins after
    it — that would invert the sequence."""
    future_open = A(D(2027, 1, 1), None, "wheat")
    assert open_assignment_to_close([future_open], D(2026, 8, 6)) is None


@pytest.mark.parametrize("on", [D(2026, 3, 9), D(2026, 3, 10), D(2026, 3, 11)])
def test_exactly_one_assignment_is_current_across_a_handover(on: date) -> None:
    """No gap and no double-cover on either side of the changeover date."""
    rows = [A(D(2025, 11, 1), D(2026, 3, 10), "tomato"), A(D(2026, 3, 10), None, "potato")]
    matches = [r for r in rows if is_active_on(r, on)]
    assert len(matches) == 1
