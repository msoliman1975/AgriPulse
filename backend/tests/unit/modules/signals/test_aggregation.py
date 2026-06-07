"""CS-6 unit tests — pure-Python aggregation reference.

These mirror the SQL CASE expression in snapshot.py exactly. If the
SQL rules change, update both sites + this test file in lockstep.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.signals.aggregation import (
    AggregatedValue,
    ObservationRow,
    aggregate_observations,
)


def _obs(value: float | str, *, days_ago: int = 0, now: datetime | None = None) -> ObservationRow:
    """Numeric observation `days_ago` before `now` (defaults to UTC now)."""
    base = now or datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    return ObservationRow(
        time=base - timedelta(days=days_ago),
        value_numeric=Decimal(str(value)),
    )


NOW = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)


class TestEmptyAndNullPaths:
    def test_empty_input_returns_none(self) -> None:
        assert (
            aggregate_observations(
                [], value_kind="numeric", aggregation="mean", window_days=None, now=NOW
            )
            is None
        )

    def test_window_excludes_everything_returns_none(self) -> None:
        # Only observations older than the window.
        out = aggregate_observations(
            [_obs(5, days_ago=30, now=NOW), _obs(7, days_ago=45, now=NOW)],
            value_kind="numeric",
            aggregation="mean",
            window_days=7,
            now=NOW,
        )
        assert out is None

    def test_all_in_window_have_null_numeric_returns_none(self) -> None:
        # Pathological: observations exist but value_numeric is NULL.
        out = aggregate_observations(
            [
                ObservationRow(time=NOW - timedelta(days=1), value_numeric=None),
            ],
            value_kind="numeric",
            aggregation="mean",
            window_days=7,
            now=NOW,
        )
        assert out is None


class TestLatestPath:
    """aggregation='latest' OR non-numeric value_kind."""

    def test_latest_returns_most_recent(self) -> None:
        # Newest is the days_ago=0 one.
        out = aggregate_observations(
            [_obs(1, days_ago=10), _obs(99, days_ago=0), _obs(50, days_ago=5)],
            value_kind="numeric",
            aggregation="latest",
            window_days=None,
            now=NOW,
        )
        assert out is not None
        assert out.value_numeric == Decimal("99")
        assert out.time == NOW

    def test_non_numeric_kind_ignores_aggregation_rule(self) -> None:
        # Categorical signal with aggregation='mean' should still return
        # the latest row's value, never average (which would be nonsense).
        rows = [
            ObservationRow(time=NOW - timedelta(days=2), value_categorical="red"),
            ObservationRow(time=NOW - timedelta(days=1), value_categorical="green"),
        ]
        out = aggregate_observations(
            rows,
            value_kind="categorical",
            aggregation="mean",  # misconfigured — should be ignored
            window_days=None,
            now=NOW,
        )
        assert out is not None
        assert out.value_categorical == "green"
        assert out.value_numeric is None

    def test_latest_carries_all_value_columns(self) -> None:
        # Multi-kind row — latest path returns every column as-is.
        rows = [
            ObservationRow(
                time=NOW,
                value_numeric=Decimal("12"),
                value_boolean=True,
                value_event="harvest",
                value_categorical="ripe",
            )
        ]
        out = aggregate_observations(
            rows, value_kind="numeric", aggregation="latest", window_days=None, now=NOW
        )
        assert isinstance(out, AggregatedValue)
        assert out.value_numeric == Decimal("12")
        assert out.value_boolean is True
        assert out.value_event == "harvest"
        assert out.value_categorical == "ripe"


class TestAggregateRules:
    """aggregation ∈ {mean, median, max, min} on numeric kind."""

    @pytest.mark.parametrize(
        ("rule", "expected"),
        [
            ("mean", Decimal("4")),
            ("median", Decimal("4")),
            ("max", Decimal("7")),
            ("min", Decimal("1")),
        ],
    )
    def test_all_history_window(self, rule: str, expected: Decimal) -> None:
        # Values [1, 4, 7] — mean and median both 4, max 7, min 1.
        rows = [_obs(1, days_ago=10), _obs(4, days_ago=5), _obs(7, days_ago=0)]
        out = aggregate_observations(
            rows,
            value_kind="numeric",
            aggregation=rule,  # type: ignore[arg-type]
            window_days=None,
            now=NOW,
        )
        assert out is not None
        assert out.value_numeric == expected

    def test_window_filters_old_rows(self) -> None:
        rows = [
            _obs(100, days_ago=30),  # outside 7d window
            _obs(2, days_ago=3),  # inside
            _obs(4, days_ago=1),  # inside
        ]
        out = aggregate_observations(
            rows,
            value_kind="numeric",
            aggregation="mean",
            window_days=7,
            now=NOW,
        )
        assert out is not None
        # 100 excluded — mean is (2 + 4) / 2 = 3.
        assert out.value_numeric == Decimal("3")

    def test_aggregated_time_is_window_max(self) -> None:
        rows = [_obs(1, days_ago=5), _obs(2, days_ago=2), _obs(3, days_ago=1)]
        out = aggregate_observations(
            rows,
            value_kind="numeric",
            aggregation="mean",
            window_days=None,
            now=NOW,
        )
        assert out is not None
        # MAX(time) of contributing rows = days_ago=1.
        assert out.time == NOW - timedelta(days=1)

    def test_median_even_count(self) -> None:
        # Even count: median is mean of two middle values.
        rows = [_obs(1, days_ago=0), _obs(2, days_ago=1), _obs(4, days_ago=2), _obs(8, days_ago=3)]
        out = aggregate_observations(
            rows,
            value_kind="numeric",
            aggregation="median",
            window_days=None,
            now=NOW,
        )
        assert out is not None
        # Middle two are 2 and 4 → median 3.
        assert out.value_numeric == Decimal("3")

    def test_single_observation(self) -> None:
        rows = [_obs(42, days_ago=0)]
        for rule in ("mean", "median", "max", "min"):
            out = aggregate_observations(
                rows,
                value_kind="numeric",
                aggregation=rule,  # type: ignore[arg-type]
                window_days=None,
                now=NOW,
            )
            assert out is not None
            assert out.value_numeric == Decimal("42"), rule


class TestSnapshotImportSmoke:
    """Smoke: the SQL in snapshot.py at least parses and is callable.
    Real behaviour is integration-tested against postgres."""

    def test_snapshot_module_imports(self) -> None:
        from app.modules.signals import snapshot

        assert callable(snapshot.load_snapshot)
        assert callable(snapshot._to_decimal)

    def test_snapshot_sql_does_not_template_error(self) -> None:
        # Constructing the snapshot SQL string fires the f-string
        # interpolation around _AGGREGATE_SQL. If a syntax error
        # creeps in (e.g. unbalanced quotes from a future edit), this
        # import-time assertion catches it before the first request.
        from app.modules.signals.snapshot import _AGGREGATE_SQL

        assert "AVG(o.value_numeric)" in _AGGREGATE_SQL
        assert "PERCENTILE_CONT" in _AGGREGATE_SQL
        assert "MAX(o.value_numeric)" in _AGGREGATE_SQL
        assert "MIN(o.value_numeric)" in _AGGREGATE_SQL


class TestCountAndSum:
    """CS-14 — count (any value_kind) + sum (numeric)."""

    def test_sum_numeric(self) -> None:
        out = aggregate_observations(
            [_obs(1), _obs(2), _obs(3)],
            value_kind="numeric",
            aggregation="sum",
            window_days=None,
            now=NOW,
        )
        assert out == AggregatedValue(time=NOW, value_numeric=Decimal("6"))

    def test_count_numeric_counts_rows(self) -> None:
        out = aggregate_observations(
            [_obs(10), _obs(20), _obs(30)],
            value_kind="numeric",
            aggregation="count",
            window_days=None,
            now=NOW,
        )
        assert out is not None
        assert out.value_numeric == Decimal("3")

    def test_count_respects_window(self) -> None:
        out = aggregate_observations(
            [_obs(1, days_ago=1), _obs(2, days_ago=5), _obs(3, days_ago=40)],
            value_kind="numeric",
            aggregation="count",
            window_days=14,
            now=NOW,
        )
        assert out is not None
        assert out.value_numeric == Decimal("2")  # the 40-day-old row is excluded

    def test_count_works_for_non_numeric_kind(self) -> None:
        # Pest-sighting events have no value_numeric, but count still works
        # by counting the rows (mirrors SQL COUNT(*)). CS-14 edge case.
        rows = [
            ObservationRow(time=NOW - timedelta(days=1), value_event="aphids"),
            ObservationRow(time=NOW - timedelta(days=2), value_event="aphids"),
            ObservationRow(time=NOW - timedelta(days=3), value_event="mites"),
        ]
        out = aggregate_observations(
            rows, value_kind="event", aggregation="count", window_days=14, now=NOW
        )
        assert out is not None
        assert out.value_numeric == Decimal("3")

    def test_count_non_numeric_empty_window_returns_none(self) -> None:
        rows = [ObservationRow(time=NOW - timedelta(days=40), value_event="aphids")]
        out = aggregate_observations(
            rows, value_kind="event", aggregation="count", window_days=14, now=NOW
        )
        assert out is None
