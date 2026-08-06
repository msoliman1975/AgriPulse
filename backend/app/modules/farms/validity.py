"""Valid-time helpers for crop assignments — pure, no DB, no I/O.

One definition of "current", shared by the block drawer, the reports, the
phenology sweep and the decision-tree context. Before this, "current" was the
stored ``block_crops.is_current`` flag, which is only ever flipped when someone
assigns a new crop — so an assignment that ended in March still read as current
in August. Deriving it from the range is what makes time pass.

The range is **half-open**, ``[effective_from, effective_to)``. The last day
under a crop is the day *before* ``effective_to``, which is what lets one
assignment end and the next start on the same date without overlapping. Every
comparison here follows that rule; getting it wrong by a day in one place and
not another is how two surfaces come to disagree about which crop is planted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any


def is_active_on(assignment: Any, on: date) -> bool:
    """Does this assignment's range contain ``on``?

    >>> from datetime import date
    >>> class A: effective_from = date(2026, 1, 1); effective_to = date(2026, 4, 1)
    >>> is_active_on(A(), date(2026, 3, 31))
    True
    >>> is_active_on(A(), date(2026, 4, 1))   # half-open: `to` is excluded
    False
    """
    start = assignment.effective_from
    end = assignment.effective_to
    if start is None or start > on:
        return False
    return end is None or end > on


def current_assignment(assignments: Iterable[Any], on: date) -> Any | None:
    """The one assignment whose range contains ``on``, or ``None``.

    A block has at most one — the ``ex_block_crops_no_overlap`` exclusion
    constraint guarantees it. When several somehow match (a caller passing
    soft-deleted rows, which the constraint excludes), the latest start wins so
    the answer is at least deterministic rather than row-order dependent.
    """
    matches = [a for a in assignments if is_active_on(a, on)]
    if not matches:
        return None
    return max(matches, key=lambda a: a.effective_from)


def state_on(assignment: Any, on: date) -> str:
    """``past`` | ``current`` | ``scheduled`` — what the history list labels."""
    if is_active_on(assignment, on):
        return "current"
    if assignment.effective_from > on:
        return "scheduled"
    return "past"


def overlaps(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    """Half-open range overlap, mirroring the DB's ``daterange && daterange``.

    The service checks this before writing so the user gets a message naming
    the conflicting assignment, rather than an IntegrityError. The constraint
    is still the authority — this is the courtesy, not the guard.

    >>> from datetime import date
    >>> overlaps(date(2026,1,1), date(2026,3,1), date(2026,3,1), None)
    False
    >>> overlaps(date(2026,1,1), date(2026,3,2), date(2026,3,1), None)
    True
    """
    # Each range ends at or before the other starts => disjoint. `to is None`
    # is +infinity, so an open range only fails to overlap when the *other*
    # one ends first.
    a_ends_first = a_to is not None and a_to <= b_from
    b_ends_first = b_to is not None and b_to <= a_from
    return not (a_ends_first or b_ends_first)


def find_conflict(
    assignments: Sequence[Any],
    *,
    new_from: date,
    new_to: date | None,
    exclude_id: Any = None,
    closing_id: Any = None,
) -> Any | None:
    """The first existing assignment the proposed range would collide with.

    ``closing_id`` is the open-ended assignment the caller intends to close at
    ``new_from``; it is skipped because after the auto-close it will end
    exactly where the new one starts, which is adjacent, not overlapping.
    """
    for existing in assignments:
        if exclude_id is not None and existing.id == exclude_id:
            continue
        if closing_id is not None and existing.id == closing_id:
            continue
        if overlaps(existing.effective_from, existing.effective_to, new_from, new_to):
            return existing
    return None


def open_assignment_to_close(assignments: Iterable[Any], new_from: date) -> Any | None:
    """The ongoing assignment a new one starting at ``new_from`` should close.

    Only an open-ended row that already started: closing a *bounded* one would
    silently rewrite a period the user explicitly set an end for.
    """
    candidates = [a for a in assignments if a.effective_to is None and a.effective_from <= new_from]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a.effective_from)
