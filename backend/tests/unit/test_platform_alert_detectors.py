"""Pure-logic guards for the platform alert detectors.

The SQL is covered by the integration test; what is pinned here is the
small amount of judgement that lives in Python, because each piece of it
encodes a decision that is easy to "tidy" into a bug later.
"""

from __future__ import annotations

from app.modules.platform_alerts.detectors import (
    DETECTORS,
    STREAM_INDEX,
    STREAM_OPTICAL,
    STREAM_THERMAL,
    STREAM_WEATHER,
    SWEEP_KINDS,
    Thresholds,
    _age_phrase,
)

TH = Thresholds(
    weather_warn_hours=26,
    weather_crit_hours=50,
    optical_warn_hours=144,
    optical_crit_hours=240,
    thermal_warn_hours=288,
    thermal_crit_hours=480,
    peer_lag_hours=26,
    stuck_job_hours=6,
    streak_threshold=3,
    new_subscription_grace_hours=26,
)


def test_index_calc_rides_the_optical_ceiling() -> None:
    """Index rows are computed from optical scenes, so they can never be
    fresher than the imagery behind them. Giving index_calc its own tighter
    ceiling would alert on the satellite revisit rather than on us."""
    assert TH.for_stream(STREAM_INDEX) == TH.for_stream(STREAM_OPTICAL)


def test_each_stream_maps_to_its_own_ceiling() -> None:
    assert TH.for_stream(STREAM_WEATHER) == (26, 50)
    assert TH.for_stream(STREAM_OPTICAL) == (144, 240)
    assert TH.for_stream(STREAM_THERMAL) == (288, 480)


def test_optical_ceiling_survives_a_sentinel2_revisit_gap() -> None:
    """The warning ceiling must sit above the worst-case revisit, or every
    farm alerts merely for being between passes.

    Sentinel-2 over a single tile is served by one relative orbit, so the
    gap between usable passes reaches 5 days. Measured on prod: Green Farm
    went 08-15 -> 08-17 -> 08-20 with nothing wrong.
    """
    worst_case_revisit_hours = 5 * 24
    warn, crit = TH.for_stream(STREAM_OPTICAL)
    assert warn > worst_case_revisit_hours
    assert crit > warn


def test_weather_ceiling_is_one_missed_poll_plus_slack() -> None:
    """Weather polls daily, so anything under a day is normal and anything
    past ~a day plus slack is a missed poll."""
    warn, crit = TH.for_stream(STREAM_WEATHER)
    assert 24 < warn <= 30
    assert crit >= 2 * 24


def test_task_error_is_not_auto_resolved_by_absence() -> None:
    """The load-bearing invariant of the whole sweep.

    `task_error` alerts are written by a Celery signal, never by the sweep.
    If the kind were listed in SWEEP_KINDS, the very next sweep would find
    no such finding, conclude the problem was fixed, and close it — so a
    task failing on every run would flap open and shut forever and never be
    on screen when anyone looked.
    """
    assert "task_error" not in SWEEP_KINDS


def test_sweep_kinds_cover_every_detector() -> None:
    """Conversely, every kind the sweep *does* recompute must be listed, or
    its alerts would never close on their own and the list would only ever
    grow."""
    assert set(SWEEP_KINDS) == {"stream_silent", "peer_lag", "failure_streak", "stuck_job"}
    # Four sweep detectors, four sweep-resolvable kinds.
    assert len(DETECTORS) == 4


def test_age_phrase_switches_unit_at_readable_boundaries() -> None:
    assert _age_phrase(0.5) == "30 minutes"
    assert _age_phrase(3) == "3.0 hours"
    assert _age_phrase(47) == "47.0 hours"
    # Past two days an hour count stops being scannable.
    assert _age_phrase(72) == "3.0 days"
