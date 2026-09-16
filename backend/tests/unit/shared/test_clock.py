"""Unit tests for `app.shared.clock`.

The clock is what lets a demo-history replay write past timestamps. Two
things have to hold for that to be safe: the real clock is returned unless
a replay explicitly asks otherwise, and the simulated value never outlives
the block that set it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.shared import clock

AT = datetime(2025, 3, 4, 10, 0, tzinfo=UTC)


def test_now_returns_the_real_time_by_default() -> None:
    before = datetime.now(UTC)
    value = clock.now()
    after = datetime.now(UTC)
    assert before <= value <= after
    assert value.tzinfo is not None


def test_default_state_is_not_simulated() -> None:
    assert clock.is_simulated() is False
    assert clock.simulated_now() is None


def test_simulate_moves_the_clock() -> None:
    with clock.simulate(AT):
        assert clock.now() == AT
        assert clock.today() == AT.date()
        assert clock.is_simulated() is True
        assert clock.simulated_now() == AT


def test_simulate_restores_the_previous_value_on_exit() -> None:
    with clock.simulate(AT):
        pass
    assert clock.is_simulated() is False
    assert clock.simulated_now() is None


def test_simulate_restores_the_previous_value_after_an_error() -> None:
    """A replay step that raises must not leave the clock stopped."""
    with pytest.raises(RuntimeError), clock.simulate(AT):
        raise RuntimeError("step failed")
    assert clock.is_simulated() is False


def test_simulate_nests() -> None:
    inner = AT + timedelta(days=1)
    with clock.simulate(AT):
        with clock.simulate(inner):
            assert clock.now() == inner
        assert clock.now() == AT
    assert clock.is_simulated() is False


def test_simulate_rejects_a_naive_datetime() -> None:
    """A naive value would move every replayed row by the local offset."""
    with (
        pytest.raises(ValueError, match="timezone-aware"),
        clock.simulate(datetime(2025, 3, 4, 10, 0)),
    ):
        pass


def test_simulate_converts_to_utc() -> None:
    cairo = timezone(timedelta(hours=2))
    with clock.simulate(datetime(2025, 3, 4, 12, 0, tzinfo=cairo)):
        assert clock.now() == AT
        assert clock.now().tzinfo is UTC


def test_pg_setting_name_does_not_collide_with_the_rls_settings() -> None:
    """The row-level security policies read `app.*`. Stay out of that space."""
    assert clock.PG_SETTING == "agripulse.now"
    assert not clock.PG_SETTING.startswith("app.")


async def _read_clock() -> bool:
    return clock.is_simulated()


def test_a_child_task_inherits_the_simulated_clock() -> None:
    """A replay awaits the engine, so the value must cross `create_task`."""

    async def main() -> bool:
        with clock.simulate(AT):
            return await asyncio.create_task(_read_clock())

    assert asyncio.run(main()) is True


def test_work_started_outside_the_block_keeps_the_real_clock() -> None:
    """Nothing outside a `simulate` block ever sees a simulated time."""

    async def main() -> bool:
        return await asyncio.create_task(_read_clock())

    with clock.simulate(AT):
        pass
    assert asyncio.run(main()) is False


def test_real_now_ignores_the_simulation() -> None:
    """A guard must not read the instant it is checking."""
    past = datetime(2024, 3, 1, 12, tzinfo=UTC)

    with clock.simulate(past):
        assert clock.now() == past
        assert clock.real_now() > past
        assert clock.real_now().tzinfo is UTC
