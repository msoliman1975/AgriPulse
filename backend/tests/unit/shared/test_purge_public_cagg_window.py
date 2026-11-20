"""The tenant-purge refresh of the public usage aggregates stops where the
production policy stops (end_offset => 1 hour), never in the future.

Its window is widened outward and padded by the widest bucket, so for a purge
of recent events it reached past the clock. Materialising today's bucket moved
the aggregate's watermark ahead of now, and real-time aggregation only reads
raw rows newer than the watermark: every event written after a purge vanished
from `usage_daily` until the next day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.shared.purge import engine as purge_engine


class _Conn:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls

    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, _stmt: Any, params: dict[str, Any]) -> None:
        self.calls.append(params)


class _Engine:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls

    def connect(self) -> _Conn:
        return _Conn(self.calls)

    async def dispose(self) -> None:
        return None


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(purge_engine, "create_async_engine", lambda *a, **k: _Engine(seen))
    return seen


async def test_a_recent_window_stops_an_hour_short_of_now(calls: list[dict[str, Any]]) -> None:
    now = datetime.now(UTC)
    window = (now - timedelta(days=1), now - timedelta(days=1) + timedelta(minutes=1))
    refreshed = await purge_engine.refresh_public_caggs(engine_url="x", window=window)
    assert refreshed  # both views still refreshed
    assert calls
    for params in calls:
        assert params["end"] <= datetime.now(UTC) - timedelta(
            minutes=59
        ), f"refresh ran to {params['end']}, past where the policy stops"
        # The start still pads outward to whole buckets.
        assert params["start"] < window[0]


async def test_an_old_window_is_left_as_padded(calls: list[dict[str, Any]]) -> None:
    then = datetime(2025, 3, 10, 13, 5, tzinfo=UTC)
    await purge_engine.refresh_public_caggs(engine_url="x", window=(then, then))
    assert {p["end"] for p in calls} == {datetime(2025, 3, 17, tzinfo=UTC)}
