"""Unit tests for `_write_trial_term` in `app.modules.billing.tasks`.

The trial dates must come from `app.shared.clock`, not the wall clock. A
demo-history replay moves the clock to a past instant, and a trial term
written during that replay has to start on the simulated date.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.modules.billing.tasks import _write_trial_term
from app.shared import clock

AT = datetime(2025, 3, 4, 10, 0, tzinfo=UTC)


class _RecordingSession:
    def __init__(self) -> None:
        self.params: dict[str, Any] | None = None

    async def execute(self, _statement: Any, params: dict[str, Any]) -> None:
        self.params = params


async def _write(session: _RecordingSession, trial_days: int = 30) -> None:
    await _write_trial_term(
        session,
        tenant_id=uuid4(),
        trial_days=trial_days,
        max_area_feddan=100,
        max_farms=2,
        max_seats=5,
    )


async def test_trial_dates_follow_the_simulated_clock() -> None:
    session = _RecordingSession()
    with clock.simulate(AT):
        await _write(session)
    assert session.params is not None
    assert session.params["starts"] == AT.date()
    assert session.params["ends"] == AT.date() + timedelta(days=30)


async def test_trial_dates_use_the_real_clock_by_default() -> None:
    session = _RecordingSession()
    await _write(session, trial_days=7)
    assert session.params is not None
    assert session.params["starts"] == clock.today()
    assert session.params["ends"] == clock.today() + timedelta(days=7)
