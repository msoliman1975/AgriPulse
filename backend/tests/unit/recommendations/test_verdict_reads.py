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
    _leaf_labels,
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


# ---- the leaf is named, not coded -----------------------------------------
#
# The reasoning card's last line printed `leaf_dry_medium` — the tree
# author's handle for the leaf — on the one line that states the answer. The
# label is already in the walk, on the step that carries no match, because a
# leaf is the answer rather than a check.


def _step(node_id: str, matched: bool | None, label: str | None) -> dict[str, Any]:
    return {"node_id": node_id, "matched": matched, "label_en": label, "label_ar": None}


def test_the_leaf_is_the_step_that_carries_no_match() -> None:
    labels = _leaf_labels(
        [
            _step("root", False, "Is it saturated?"),
            _step("medium", True, "Is it above the bound?"),
            _step("leaf_dry_medium", None, "Irrigate within 24 hours"),
        ]
    )

    assert labels == ("Irrigate within 24 hours", None)


def test_the_leaf_is_read_from_the_end() -> None:
    """A malformed walk with an unmatched step in the middle must not be
    mistaken for the conclusion."""
    labels = _leaf_labels(
        [
            _step("odd", None, "Not the answer"),
            _step("check", True, "A real check"),
            _step("leaf", None, "The answer"),
        ]
    )

    assert labels[0] == "The answer"


def test_a_pruned_walk_names_no_leaf() -> None:
    """Retention prunes the run behind a verdict. The caller then keeps
    showing the node id, which is worse to read but never wrong."""
    assert _leaf_labels([]) == (None, None)


def test_a_leaf_with_a_blank_label_names_no_leaf() -> None:
    assert _leaf_labels([_step("leaf", None, "")]) == (None, None)


def test_both_languages_come_back_when_the_leaf_carries_both() -> None:
    labels = _leaf_labels(
        [{"node_id": "leaf", "matched": None, "label_en": "Irrigate", "label_ar": "اسقِ"}]
    )

    assert labels == ("Irrigate", "اسقِ")
