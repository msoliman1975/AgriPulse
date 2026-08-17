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
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.modules.observer.repository import (
    BUCKETS,
    FARM_ONLY_JOB_STATUSES,
    JOB_STATUSES,
    _d,
    _ts,
)

_MIGRATION = (
    Path(__file__).resolve().parents[4]
    / "migrations"
    / "tenant"
    / "versions"
    / "0003_imagery_subscriptions_and_indices.py"
)

_OBSERVER = Path(__file__).resolve().parents[4] / "app" / "modules" / "observer"

# Every TimescaleDB hypertable Observer reads. A time predicate against one of
# these must be an interpolated literal; see the module guard below.
_HYPERTABLES = (
    "block_index_aggregates",
    "block_grid_aggregates",
    "weather_observations",
    "weather_forecasts",
)


def test_ts_renders_a_timestamptz_literal() -> None:
    rendered = _ts(datetime(2026, 6, 14, 8, 37, tzinfo=UTC))
    assert rendered == "TIMESTAMPTZ '2026-06-14T08:37:00+00:00'"


def test_d_renders_a_date_literal() -> None:
    rendered = _d(date(2026, 6, 14))
    assert rendered == "DATE '2026-06-14'"


@pytest.mark.parametrize(
    "hostile",
    ["2026-01-01' OR '1'='1", "", datetime(2026, 6, 14, 8, 37, tzinfo=UTC)],
)
def test_d_refuses_anything_that_is_not_a_plain_date(hostile: object) -> None:
    """A `datetime` is rejected too, not just strings.

    `datetime` subclasses `date`, so a naive isinstance check would accept one
    and silently truncate it into a `DATE` literal — the time component would
    vanish and the query would answer for the wrong midnight.
    """
    with pytest.raises(TypeError, match="must be a date"):
        _d(hostile)  # type: ignore[arg-type]


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


def test_every_hypertable_read_carries_an_interpolated_time_bound() -> None:
    """No query may reach a hypertable without a literal time bound.

    This is the guard the `list_scenes` outage needed and did not have. Its
    two correlated subqueries were bounded only by `a.time = j.scene_datetime`
    — a column reference. A correlated column gives the planner nothing to
    exclude chunks with, and because asyncpg prepares the statement Postgres
    switches to a generic plan after a few executions and locks *every* chunk
    of both hypertables. On a ~500-chunk tenant that exhausts
    `max_locks_per_transaction`, and the endpoint returns `out of shared
    memory` for every window — including windows that worked moments before,
    because the first few executions still got a custom plan.

    Reviewing for this by eye does not work: the bounds look redundant next to
    the correlation, which is exactly why they were left out and why someone
    will eventually delete them. So the rule is enforced against the source.
    """
    offenders: list[str] = []
    for path in sorted(_OBSERVER.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not any(f"{h} " in line or line.rstrip().endswith(h) for h in _HYPERTABLES):
                continue
            if not ("FROM" in line or "JOIN" in line):
                continue
            # The predicate list of this FROM/JOIN: everything up to the end of
            # the subquery or the start of the next one.
            block = "\n".join(lines[i : i + 12])
            if "{_ts(" in block or "{_d(" in block:
                continue
            offenders.append(f"{path.name}:{i + 1}: {line.strip()}")

    assert not offenders, (
        "hypertable read with no interpolated time bound — the planner cannot "
        "exclude chunks and will lock all of them under a generic plan:\n  "
        + "\n  ".join(offenders)
    )


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
    # `JOB_STATUSES` now spans both job tables, so the block CHECK is
    # exactly its non-farm half rather than the whole thing. Comparing that
    # half exactly keeps the guard as tight as it was — a status added to
    # the block CHECK still fails here — while letting the farm table
    # contribute its own vocabulary.
    assert declared == set(JOB_STATUSES) - FARM_ONLY_JOB_STATUSES, (
        "JOB_STATUSES has drifted from the migration's CHECK constraint: "
        f"migration-only={declared - set(JOB_STATUSES)}, "
        f"constant-only={set(JOB_STATUSES) - FARM_ONLY_JOB_STATUSES - declared}"
    )
    # And the farm half must not silently overlap the block one, or a
    # future rename would leave the guard comparing a set against itself.
    assert not (FARM_ONLY_JOB_STATUSES & declared)
