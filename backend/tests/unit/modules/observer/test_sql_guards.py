"""Guards on the two things Observer's SQL interpolates.

Everything else in the repository travels as a bind parameter. Time bounds
cannot — a bound parameter kills TimescaleDB chunk exclusion — and the
histogram's `date_trunc` unit cannot. Both are therefore checked here rather
than trusted to convention.

Also pins the job-status constant against the migration that defines it. The
constant is a copy, and a copy that drifts silently is the failure mode
`conditionEdit.ts` taught us to test for: the histogram would quietly stop
counting a status nobody remembered Observer mirrored.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.modules.observer.repository import BUCKETS, JOB_STATUSES, _ts

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations"
    / "tenant"
    / "versions"
    / "0003_imagery_subscriptions_and_indices.py"
)


def test_ts_renders_a_timestamptz_literal() -> None:
    rendered = _ts(datetime(2026, 6, 14, 8, 37, tzinfo=UTC))
    assert rendered == "TIMESTAMPTZ '2026-06-14T08:37:00+00:00'"


@pytest.mark.parametrize(
    "hostile",
    ["2026-01-01' OR '1'='1", "now()", "'; DROP TABLE blocks; --", ""],
)
def test_ts_refuses_anything_that_is_not_a_datetime(hostile: str) -> None:
    """The interpolation is safe *because* this raises.

    A caller string can never reach the query text: the router parses these
    to `datetime` and this guard makes that a hard invariant rather than a
    reviewer's assumption.
    """
    with pytest.raises(TypeError, match="must be a datetime"):
        _ts(hostile)  # type: ignore[arg-type]


def test_bucket_units_are_a_closed_set() -> None:
    """`date_trunc('{unit}', ...)` is interpolated, so the set must be fixed."""
    assert set(BUCKETS) == {"day", "week", "month"}
    assert all(v == k for k, v in BUCKETS.items())
    assert all(re.fullmatch(r"[a-z]+", v) for v in BUCKETS.values())


def test_job_status_constant_matches_the_migration_check_constraint() -> None:
    """JOB_STATUSES mirrors the CHECK on `imagery_ingestion_jobs`.

    Drift here is invisible at runtime: a status added upstream would simply
    stop appearing in the histogram and the scene-status filter, with no error
    anywhere. Reading the migration is the only way to catch it in CI.
    """
    source = _MIGRATION.read_text(encoding="utf-8")
    # The constraint is written as implicitly-concatenated string literals
    # across several lines, so match the region between its opening and its
    # name rather than trying to pin the exact line breaks.
    marker = '"status IN ("'
    assert marker in source, "could not find the status CHECK in tenant migration 0003"
    start = source.index(marker)
    end = source.index('name="ck_imagery_ingestion_jobs_status"', start)
    declared = set(re.findall(r"'([a-z_]+)'", source[start:end]))
    assert declared == set(JOB_STATUSES), (
        "JOB_STATUSES has drifted from the migration's CHECK constraint: "
        f"migration-only={declared - set(JOB_STATUSES)}, "
        f"constant-only={set(JOB_STATUSES) - declared}"
    )
