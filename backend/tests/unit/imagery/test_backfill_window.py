"""Unit tests for the imagery discovery-window resolver.

Covers the branch that the one-shot historical backfill relies on: an
explicit window must override the watermark/floor entirely, while normal
discovery stays watermark-driven with the cold-start floor fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.settings import get_settings
from app.modules.imagery.tasks import _resolve_discovery_window

_NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)


def test_explicit_window_overrides_watermark() -> None:
    settings = get_settings()
    start = datetime(2025, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 1, tzinfo=UTC)
    # Even with a live watermark present, the explicit window wins verbatim.
    sub = {"last_successful_ingest_at": datetime(2026, 6, 20, tzinfo=UTC)}

    got_start, got_end = _resolve_discovery_window(
        subscription=sub,
        settings=settings,
        now=_NOW,
        window_start_override=start,
        window_end_override=end,
    )
    assert got_start == start
    assert got_end == end


def test_explicit_start_defaults_end_to_now() -> None:
    settings = get_settings()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    got_start, got_end = _resolve_discovery_window(
        subscription={"last_successful_ingest_at": None},
        settings=settings,
        now=_NOW,
        window_start_override=start,
        window_end_override=None,
    )
    assert got_start == start
    assert got_end == _NOW


def test_watermark_window_pulls_back_by_lookback() -> None:
    settings = get_settings()
    watermark = datetime(2026, 6, 20, tzinfo=UTC)
    got_start, got_end = _resolve_discovery_window(
        subscription={"last_successful_ingest_at": watermark},
        settings=settings,
        now=_NOW,
        window_start_override=None,
        window_end_override=None,
    )
    assert got_start == watermark - timedelta(hours=settings.imagery_discovery_lookback_hours)
    assert got_end == _NOW


def test_cold_start_uses_the_floor() -> None:
    """No watermark means reach back to the cold-start floor, and no further.

    The floor used to be pulled back by the lookback as well, which put the
    start 48h beyond the documented bound. It is a floor, so it is now the
    limit for every branch.
    """
    settings = get_settings()
    got_start, got_end = _resolve_discovery_window(
        subscription={"last_successful_ingest_at": None},
        settings=settings,
        now=_NOW,
        window_start_override=None,
        window_end_override=None,
    )
    assert got_start == _NOW - timedelta(days=settings.imagery_backfill_floor_days)
    assert got_end == _NOW


def test_a_watermark_older_than_the_floor_is_clamped_to_it() -> None:
    """The watermark is now a scene sensing time, so it stops moving when the
    imagery stops. A subscription whose last scene was two years ago must not
    ask the catalogue for two years."""
    settings = get_settings()
    got_start, _ = _resolve_discovery_window(
        subscription={"last_successful_ingest_at": _NOW - timedelta(days=730)},
        settings=settings,
        now=_NOW,
        window_start_override=None,
        window_end_override=None,
    )
    assert got_start == _NOW - timedelta(days=settings.imagery_backfill_floor_days)


def test_a_recent_watermark_still_wins_over_the_floor() -> None:
    """The clamp must not swallow the normal case."""
    settings = get_settings()
    watermark = _NOW - timedelta(days=5)
    got_start, _ = _resolve_discovery_window(
        subscription={"last_successful_ingest_at": watermark},
        settings=settings,
        now=_NOW,
        window_start_override=None,
        window_end_override=None,
    )
    assert got_start == watermark - timedelta(hours=settings.imagery_discovery_lookback_hours)
