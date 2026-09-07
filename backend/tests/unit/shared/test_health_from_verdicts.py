"""Health from what the trees actually said.

A verdict exists for every leaf a tree reaches, including the leaves that
find nothing wrong, so it is a better source than counting alerts: an alert
only exists when something is wrong, and its absence never distinguished
"checked and fine" from "nothing looked".

The rules these tests pin:

  * verdicts decide alone when there are any, because an alert leaf writes
    both an alert and a verdict and reading both counts one finding twice;
  * freshness gates the healthy answer only, never a critical;
  * `na` argues for nothing — a tree that ran and had nothing to say is not
    evidence of health.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.shared.health_definition import (
    PLATFORM_DEFAULT_DEFINITION,
    AlertEvidence,
    HealthInputs,
    VerdictEvidence,
    resolve_health,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
FRESH = NOW - timedelta(hours=6)
OLD = NOW - timedelta(hours=72)


def _resolve(inputs: HealthInputs, definition=PLATFORM_DEFAULT_DEFINITION):
    return resolve_health(definition, inputs, now=NOW)


def _verdicts(*codes: str, seen: datetime = FRESH) -> HealthInputs:
    return HealthInputs(
        verdicts=tuple(VerdictEvidence(status_code=c) for c in codes),
        verdict_last_evaluated_at=seen,
    )


# ---- worst wins ----------------------------------------------------------


def test_an_alert_verdict_reads_critical() -> None:
    assert _resolve(_verdicts("good", "alert", "issue")) == ("critical", "verdict_alert")


def test_an_issue_verdict_reads_watch() -> None:
    assert _resolve(_verdicts("good", "issue", "very_good")) == ("watch", "verdict_issue")


def test_every_tree_clear_reads_healthy() -> None:
    assert _resolve(_verdicts("good", "very_good", "good")) == ("healthy", "verdict_good")


def test_na_never_outranks_a_real_answer() -> None:
    assert _resolve(_verdicts("na", "good")) == ("healthy", "verdict_good")


def test_every_verdict_na_is_not_health() -> None:
    """The trees ran and none of them had anything to say about this block.

    Same answer as no tree covering it at all, which under the platform
    default is unknown.
    """
    assert _resolve(_verdicts("na", "na")) == ("unknown", "no_tree")


# ---- freshness -----------------------------------------------------------


def test_a_stale_sweep_cannot_claim_the_block_is_fine() -> None:
    assert _resolve(_verdicts("good", seen=OLD)) == ("unknown", "stale")


def test_a_stale_sweep_does_not_hide_a_critical() -> None:
    """The direction that matters. An old alert is still an alert."""
    assert _resolve(_verdicts("alert", seen=OLD)) == ("critical", "verdict_alert")


def test_a_verdict_with_no_evaluation_time_reads_unknown() -> None:
    inputs = HealthInputs(
        verdicts=(VerdictEvidence(status_code="good"),), verdict_last_evaluated_at=None
    )

    assert _resolve(inputs) == ("unknown", "no_coverage")


# ---- verdicts replace the alert path -------------------------------------


def test_verdicts_decide_alone_when_there_are_any() -> None:
    """An alert leaf writes both an alert row and a verdict.

    Reading both would count one finding twice — and worse, an alert that a
    person has since resolved would still be counted while the tree's own
    current answer says the block is fine.
    """
    inputs = HealthInputs(
        verdicts=(VerdictEvidence(status_code="good"),),
        verdict_last_evaluated_at=FRESH,
        alerts=(AlertEvidence(severity="critical", status="open"),),
    )

    assert _resolve(inputs) == ("healthy", "verdict_good")


def test_a_block_with_no_verdicts_still_uses_the_alert_path() -> None:
    """The fallback, for a block whose sweep predates the verdict table."""
    inputs = HealthInputs(
        alerts=(AlertEvidence(severity="critical", status="open"),),
        traces_fired=1,
        last_evaluated_at=FRESH,
    )

    assert _resolve(inputs) == ("critical", "critical_alert")


def test_a_block_with_nothing_at_all_is_unknown() -> None:
    assert _resolve(HealthInputs()) == ("unknown", "no_coverage")


# ---- the cell share ------------------------------------------------------


def test_one_alert_cell_is_enough_when_no_share_is_set() -> None:
    """Unset means one cell is enough, which can never hide a finding."""
    inputs = HealthInputs(
        verdicts=(VerdictEvidence(status_code="alert", cell_id=uuid4()),),
        verdict_last_evaluated_at=FRESH,
        total_cells=100,
    )

    assert _resolve(inputs) == ("critical", "verdict_alert")


def test_a_share_that_is_not_met_holds_the_block_at_watch() -> None:
    from dataclasses import replace

    definition = replace(PLATFORM_DEFAULT_DEFINITION, cell_critical_share=0.5)
    inputs = HealthInputs(
        verdicts=tuple(VerdictEvidence(status_code="alert", cell_id=uuid4()) for _ in range(2)),
        verdict_last_evaluated_at=FRESH,
        total_cells=100,
    )

    assert _resolve(inputs, definition) == ("watch", "cell_share")


def test_a_share_that_is_met_reads_critical() -> None:
    from dataclasses import replace

    definition = replace(PLATFORM_DEFAULT_DEFINITION, cell_critical_share=0.5)
    inputs = HealthInputs(
        verdicts=tuple(VerdictEvidence(status_code="alert", cell_id=uuid4()) for _ in range(6)),
        verdict_last_evaluated_at=FRESH,
        total_cells=10,
    )

    assert _resolve(inputs, definition) == ("critical", "verdict_alert")


def test_a_block_scoped_alert_verdict_ignores_the_share() -> None:
    """It is about the whole block, so there is no share to compare."""
    from dataclasses import replace

    definition = replace(PLATFORM_DEFAULT_DEFINITION, cell_critical_share=0.9)
    inputs = HealthInputs(
        verdicts=(VerdictEvidence(status_code="alert", cell_id=None),),
        verdict_last_evaluated_at=FRESH,
        total_cells=100,
    )

    assert _resolve(inputs, definition) == ("critical", "verdict_alert")
