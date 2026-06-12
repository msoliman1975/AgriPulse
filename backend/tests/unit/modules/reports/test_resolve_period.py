"""Unit tests for the shared report-period resolver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.reports.service import resolve_period


def test_defaults_to_last_30_days() -> None:
    before = datetime.now(UTC)
    period = resolve_period(None, None)
    after = datetime.now(UTC)

    # until pins to "now"; since is 30 days before it.
    assert before <= period.until <= after
    assert period.until - period.since == timedelta(days=30)


def test_since_defaults_relative_to_explicit_until() -> None:
    until = datetime(2026, 5, 31, tzinfo=UTC)
    period = resolve_period(None, until)
    assert period.until == until
    assert period.since == until - timedelta(days=30)


def test_explicit_bounds_pass_through() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = datetime(2026, 3, 1, tzinfo=UTC)
    period = resolve_period(since, until)
    assert period.since == since
    assert period.until == until


def test_until_defaults_to_now_when_only_since_given() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    before = datetime.now(UTC)
    period = resolve_period(since, None)
    after = datetime.now(UTC)
    assert period.since == since
    assert before <= period.until <= after
