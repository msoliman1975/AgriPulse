"""What the read layer computes on top of the rows.

The SQL is checked against a real database. These cover the two things the
service decides for itself: the instant a replay is compared against, and the
single status a block reads as.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.modules.recommendations.service import (
    RecommendationsServiceImpl,
    _as_utc,
    _block_group,
)
from app.modules.recommendations.status_codes import STATUS_CODES


def _row(status: str, seen: datetime | None = None) -> dict[str, Any]:
    return {
        "status_code": status,
        "last_evaluated_at": seen or datetime(2026, 9, 1, tzinfo=UTC),
        "tree_code": "demo_v1",
    }


# ---- the replay instant ---------------------------------------------------


def test_a_naive_instant_is_stamped_utc() -> None:
    """`?at=2026-09-01T00:00` arrives with no offset.

    Subtracting a naive datetime from a timestamptz raises TypeError, so the
    comparison value is stamped before it reaches the query.
    """
    stamped = _as_utc(datetime(2026, 9, 1, 12, 0))

    assert stamped is not None
    assert stamped.tzinfo is UTC


def test_an_aware_instant_is_left_alone() -> None:
    sent = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    assert _as_utc(sent) == sent


def test_no_instant_means_now() -> None:
    assert _as_utc(None) is None


# ---- the block's single answer -------------------------------------------


def test_the_worst_status_is_what_the_block_reads_as() -> None:
    group = _block_group(
        block_id=uuid4(),
        rows=[_row("good"), _row("issue"), _row("very_good")],
        as_of=None,
    )

    assert group["worst_status"] == "issue"


def test_a_tree_with_nothing_to_say_never_outranks_a_real_answer() -> None:
    group = _block_group(block_id=uuid4(), rows=[_row("na"), _row("very_good")], as_of=None)

    assert group["worst_status"] == "very_good"


def test_a_block_no_tree_has_run_on_has_no_status() -> None:
    """Not `na`, and not `good`. Nothing has looked at it.

    A map that painted this grey would be making the same claim the old
    blank made: that something is known about the block.
    """
    group = _block_group(block_id=uuid4(), rows=[], as_of=None)

    assert group["worst_status"] is None
    assert group["last_evaluated_at"] is None
    assert group["verdicts"] == []


def test_the_block_reports_its_newest_evaluation() -> None:
    newest = datetime(2026, 9, 5, tzinfo=UTC)
    group = _block_group(
        block_id=uuid4(),
        rows=[_row("good", newest - timedelta(days=2)), _row("good", newest)],
        as_of=None,
    )

    assert group["last_evaluated_at"] == newest


def test_the_as_of_echo_is_exactly_what_the_caller_sent() -> None:
    """Echoed untouched, offset or not. Only the comparison is stamped."""
    sent = datetime(2026, 9, 1, 12, 0)

    group = _block_group(block_id=uuid4(), rows=[_row("good")], as_of=sent)

    assert group["as_of"] == sent
    assert group["as_of"].tzinfo is None


# ---- the status catalog ---------------------------------------------------


def test_the_catalog_serves_every_code_with_both_labels() -> None:
    catalog = RecommendationsServiceImpl.status_catalog()

    assert [entry["code"] for entry in catalog] == list(STATUS_CODES)
    for entry in catalog:
        assert entry["color"].startswith("#")
        assert entry["label_en"]
        assert entry["label_ar"]
        assert entry["label_en"] != entry["label_ar"]
