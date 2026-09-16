"""Single source of the current time.

Every part of the backend that needs "now" calls `clock.now()` instead of
`datetime.now(UTC)`. In normal operation the two return the same value. While
a demo-history replay is running, the clock is moved to a past instant, so the
rows the engine writes carry past timestamps instead of today's.

The database has the other half of this. `public.app_now()` reads the Postgres
setting `agripulse.now`, and application SQL calls `public.app_now()` instead
of `now()`. `app.shared.db.session` writes that setting on every transaction
while a simulated clock is active, so the Python side and the SQL side always
report the same instant.

Two limits to know about:

* The value lives in a `ContextVar`. A Celery task runs in another process, so
  the simulated time does not travel with a queued message. A replay must call
  the task function in its own process, inside `simulate(...)`.
* `simulate` is for the replay and for tests. Nothing on a request path may
  call it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime

__all__ = [
    "PG_SETTING",
    "is_simulated",
    "now",
    "real_now",
    "simulate",
    "simulated_now",
    "today",
]

# Name of the Postgres setting that carries the same instant to SQL.
# `public.app_now()` reads it. A custom name needs a dot, and the prefix
# must not collide with the `app.` settings the row-level security
# policies already use.
PG_SETTING = "agripulse.now"

_simulated: ContextVar[datetime | None] = ContextVar(
    "agripulse_simulated_now",
    default=None,
)


def now() -> datetime:
    """Return the current time, or the simulated time during a replay.

    Always timezone-aware and in UTC.
    """
    return _simulated.get() or datetime.now(UTC)


def today() -> date:
    """Return the current UTC date, or the simulated date during a replay."""
    return now().date()


def real_now() -> datetime:
    """Return the wall clock, ignoring any simulation.

    This is for a guard that has to decide whether a replay may run at all.
    A guard that asked `now()` would read the simulated instant it is
    supposed to be checking, and would approve every run. Nothing that
    writes a row may call this.
    """
    return datetime.now(UTC)


def simulated_now() -> datetime | None:
    """Return the simulated instant, or None when the real clock is in use."""
    return _simulated.get()


def is_simulated() -> bool:
    """Report whether a simulated clock is active in this context."""
    return _simulated.get() is not None


@contextmanager
def simulate(at: datetime) -> Iterator[None]:
    """Move the clock to `at` for the duration of the block.

    `at` must be timezone-aware. A naive value is rejected rather than
    assumed to be UTC, because a wrong assumption here moves every row the
    replay writes by the size of the offset and nothing reports an error.

    The previous value is restored on exit, including when the block raises,
    so nesting works and a failure cannot leave the clock stopped in the past.
    """
    if at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise ValueError(f"simulate() needs a timezone-aware datetime, got {at!r}")
    token = _simulated.set(at.astimezone(UTC))
    try:
        yield
    finally:
        _simulated.reset(token)
