"""Unit tests for the bounded health definition and its resolver.

The three cases the old rule could not tell apart get their own tests:
trees ran and passed, trees ran with no data, and no tree applies. Under
the old rule all three painted green.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest

from app.modules.alerts.schemas import AlertSeverity, AlertStatus
from app.shared.health_definition import (
    PLATFORM_DEFAULT_DEFINITION,
    AlertEvidence,
    HealthDefinition,
    HealthDefinitionError,
    HealthInputs,
    parse_definition,
    resolve_health,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
FRESH = NOW - timedelta(hours=2)


def covered(**kwargs: object) -> HealthInputs:
    """Inputs for a block a tree actually evaluated, clear, two hours ago.

    Every test that is not about coverage starts here, so a failure points
    at the rule under test and not at the coverage gate.
    """
    base: dict[str, object] = {
        "traces_clear": 1,
        "last_evaluated_at": FRESH,
    }
    base.update(kwargs)
    return HealthInputs(**base)  # type: ignore[arg-type]


def resolve(inputs: HealthInputs, definition: HealthDefinition | None = None):
    return resolve_health(definition or PLATFORM_DEFAULT_DEFINITION, inputs, now=NOW)


# ---------- The vocabulary must match the alerts module ----------------------


def test_severities_match_the_alerts_schema() -> None:
    from app.shared.health_definition import _SEVERITIES

    assert set(get_args(AlertSeverity)) == set(_SEVERITIES)


def test_statuses_match_the_alerts_schema() -> None:
    from app.shared.health_definition import _STATUSES

    assert set(get_args(AlertStatus)) == set(_STATUSES)


# ---------- Alerts decide the class ------------------------------------------


def test_open_critical_alert_reads_critical() -> None:
    inputs = covered(alerts=(AlertEvidence(severity="critical", status="open"),))
    assert resolve(inputs) == ("critical", "critical_alert")


def test_open_warning_alert_reads_watch() -> None:
    inputs = covered(alerts=(AlertEvidence(severity="warning", status="open"),))
    assert resolve(inputs) == ("watch", "warning_alert")


def test_critical_beats_warning_whatever_the_order() -> None:
    inputs = covered(
        alerts=(
            AlertEvidence(severity="warning", status="open"),
            AlertEvidence(severity="critical", status="open"),
        )
    )
    assert resolve(inputs) == ("critical", "critical_alert")


def test_info_alert_does_not_move_the_class() -> None:
    inputs = covered(alerts=(AlertEvidence(severity="info", status="open"),))
    assert resolve(inputs) == ("healthy", "all_clear")


def test_resolved_alert_is_finished_and_colours_nothing() -> None:
    inputs = covered(alerts=(AlertEvidence(severity="critical", status="resolved"),))
    assert resolve(inputs) == ("healthy", "all_clear")


def test_acknowledged_critical_stays_critical() -> None:
    """Somebody saw it. That is not the same as the block recovering."""
    inputs = covered(alerts=(AlertEvidence(severity="critical", status="acknowledged"),))
    assert resolve(inputs) == ("critical", "critical_alert")


def test_snoozed_critical_reads_watch_by_default() -> None:
    inputs = covered(alerts=(AlertEvidence(severity="critical", status="snoozed"),))
    assert resolve(inputs) == ("watch", "warning_alert")


def test_snoozed_uses_its_severity_when_snoozed_as_is_unset() -> None:
    definition = HealthDefinition(snoozed_as=None)
    inputs = covered(alerts=(AlertEvidence(severity="critical", status="snoozed"),))
    assert resolve(inputs, definition) == ("critical", "critical_alert")


def test_a_status_left_out_of_counted_statuses_is_ignored() -> None:
    definition = HealthDefinition(counted_statuses=frozenset({"open"}))
    inputs = covered(alerts=(AlertEvidence(severity="critical", status="acknowledged"),))
    assert resolve(inputs, definition) == ("healthy", "all_clear")


def test_severity_map_can_demote_warning_to_no_verdict() -> None:
    definition = HealthDefinition(
        severity_map={"critical": "critical", "warning": "healthy", "info": "healthy"}
    )
    inputs = covered(alerts=(AlertEvidence(severity="warning", status="open"),))
    assert resolve(inputs, definition) == ("healthy", "all_clear")


# ---------- Cell share --------------------------------------------------------


def test_one_critical_cell_is_enough_without_a_threshold() -> None:
    inputs = covered(
        alerts=(AlertEvidence(severity="critical", status="open", cell_id="c1"),),
        total_cells=60,
    )
    assert resolve(inputs) == ("critical", "critical_alert")


def test_one_critical_cell_in_sixty_is_watch_under_a_ten_percent_threshold() -> None:
    definition = HealthDefinition(cell_critical_share=Decimal("0.10"))
    inputs = covered(
        alerts=(AlertEvidence(severity="critical", status="open", cell_id="c1"),),
        total_cells=60,
    )
    assert resolve(inputs, definition) == ("watch", "cell_share")


def test_six_critical_cells_in_sixty_meet_a_ten_percent_threshold() -> None:
    definition = HealthDefinition(cell_critical_share=Decimal("0.10"))
    inputs = covered(
        alerts=tuple(
            AlertEvidence(severity="critical", status="open", cell_id=f"c{i}") for i in range(6)
        ),
        total_cells=60,
    )
    assert resolve(inputs, definition) == ("critical", "critical_alert")


def test_two_alerts_on_one_cell_count_as_one_cell() -> None:
    definition = HealthDefinition(cell_critical_share=Decimal("0.10"))
    inputs = covered(
        alerts=(
            AlertEvidence(severity="critical", status="open", cell_id="c1"),
            AlertEvidence(severity="critical", status="open", cell_id="c1"),
        ),
        total_cells=10,
    )
    assert resolve(inputs, definition) == ("critical", "critical_alert")


def test_a_block_scoped_critical_ignores_the_cell_threshold() -> None:
    definition = HealthDefinition(cell_critical_share=Decimal("0.90"))
    inputs = covered(
        alerts=(AlertEvidence(severity="critical", status="open"),),
        total_cells=60,
    )
    assert resolve(inputs, definition) == ("critical", "critical_alert")


def test_an_unknown_cell_count_does_not_hide_a_critical() -> None:
    definition = HealthDefinition(cell_critical_share=Decimal("0.10"))
    inputs = covered(
        alerts=(AlertEvidence(severity="critical", status="open", cell_id="c1"),),
        total_cells=0,
    )
    assert resolve(inputs, definition) == ("critical", "critical_alert")


def test_a_block_scoped_critical_wins_over_a_held_back_cell() -> None:
    definition = HealthDefinition(cell_critical_share=Decimal("0.90"))
    inputs = covered(
        alerts=(
            AlertEvidence(severity="critical", status="open", cell_id="c1"),
            AlertEvidence(severity="critical", status="open"),
        ),
        total_cells=60,
    )
    assert resolve(inputs, definition) == ("critical", "critical_alert")


# ---------- Recommendations ---------------------------------------------------


def test_recommendations_do_not_move_health_by_default() -> None:
    inputs = covered(max_recommendation_confidence=Decimal("0.99"))
    assert resolve(inputs) == ("healthy", "all_clear")


def test_a_recommendation_at_the_floor_moves_the_block_to_watch() -> None:
    definition = HealthDefinition(recommendation_floor=Decimal("0.80"))
    inputs = covered(max_recommendation_confidence=Decimal("0.80"))
    assert resolve(inputs, definition) == ("watch", "strong_recommendation")


def test_a_recommendation_below_the_floor_changes_nothing() -> None:
    definition = HealthDefinition(recommendation_floor=Decimal("0.80"))
    inputs = covered(max_recommendation_confidence=Decimal("0.50"))
    assert resolve(inputs, definition) == ("healthy", "all_clear")


def test_an_alert_outranks_a_strong_recommendation() -> None:
    definition = HealthDefinition(recommendation_floor=Decimal("0.10"))
    inputs = covered(
        alerts=(AlertEvidence(severity="critical", status="open"),),
        max_recommendation_confidence=Decimal("0.99"),
    )
    assert resolve(inputs, definition) == ("critical", "critical_alert")


# ---------- The three states the old rule could not tell apart ----------------


def test_trees_ran_and_everything_passed_is_healthy() -> None:
    inputs = HealthInputs(traces_clear=3, last_evaluated_at=FRESH)
    assert resolve(inputs) == ("healthy", "all_clear")


def test_the_sweep_never_reached_this_block_is_unknown() -> None:
    inputs = HealthInputs(last_evaluated_at=FRESH)
    assert resolve(inputs) == ("unknown", "no_coverage")


def test_a_tree_that_errored_is_unknown_not_healthy() -> None:
    inputs = HealthInputs(traces_clear=2, traces_error=1, last_evaluated_at=FRESH)
    assert resolve(inputs) == ("unknown", "no_coverage")


def test_every_tree_skipped_means_no_tree_covers_this_block() -> None:
    inputs = HealthInputs(traces_skipped=4, last_evaluated_at=FRESH)
    assert resolve(inputs) == ("unknown", "no_tree")


def test_a_tenant_can_choose_to_read_uncovered_blocks_as_healthy() -> None:
    definition = HealthDefinition(no_tree_coverage="healthy")
    inputs = HealthInputs(traces_skipped=4, last_evaluated_at=FRESH)
    assert resolve(inputs, definition) == ("healthy", "no_tree")


def test_a_fired_trace_still_counts_as_coverage() -> None:
    """A tree fired but opened only an info alert. The block was looked at."""
    inputs = HealthInputs(
        traces_fired=1,
        last_evaluated_at=FRESH,
        alerts=(AlertEvidence(severity="info", status="open"),),
    )
    assert resolve(inputs) == ("healthy", "all_clear")


# ---------- Freshness ---------------------------------------------------------


def test_an_evaluation_older_than_the_limit_is_stale() -> None:
    inputs = HealthInputs(traces_clear=1, last_evaluated_at=NOW - timedelta(hours=49))
    assert resolve(inputs) == ("unknown", "stale")


def test_an_evaluation_exactly_at_the_limit_is_still_believed() -> None:
    inputs = HealthInputs(traces_clear=1, last_evaluated_at=NOW - timedelta(hours=48))
    assert resolve(inputs) == ("healthy", "all_clear")


def test_a_missing_evaluation_time_is_not_coverage() -> None:
    inputs = HealthInputs(traces_clear=1, last_evaluated_at=None)
    assert resolve(inputs) == ("unknown", "no_coverage")


def test_staleness_never_hides_an_open_critical() -> None:
    """A real finding is never buried behind unknown."""
    inputs = HealthInputs(
        traces_clear=1,
        last_evaluated_at=NOW - timedelta(days=30),
        alerts=(AlertEvidence(severity="critical", status="open"),),
    )
    assert resolve(inputs) == ("critical", "critical_alert")


def test_missing_coverage_never_hides_an_open_critical() -> None:
    inputs = HealthInputs(alerts=(AlertEvidence(severity="critical", status="open"),))
    assert resolve(inputs) == ("critical", "critical_alert")


def test_the_stale_limit_is_read_from_the_definition() -> None:
    definition = HealthDefinition(stale_after_hours=6)
    inputs = HealthInputs(traces_clear=1, last_evaluated_at=NOW - timedelta(hours=7))
    assert resolve(inputs, definition) == ("unknown", "stale")


# ---------- The default definition -------------------------------------------


def test_the_platform_default_is_valid_and_says_what_we_think_it_says() -> None:
    d = PLATFORM_DEFAULT_DEFINITION
    assert d.version == 1
    assert d.counted_statuses == frozenset({"open", "acknowledged", "snoozed"})
    assert d.snoozed_as == "watch"
    assert d.recommendation_floor is None
    assert d.cell_critical_share is None
    assert d.stale_after_hours == 48
    assert d.no_tree_coverage == "unknown"


# ---------- Parsing rejects anything unclear ---------------------------------


def test_parse_accepts_an_empty_mapping_as_the_default() -> None:
    assert parse_definition({}) == PLATFORM_DEFAULT_DEFINITION


def test_parse_rejects_an_unknown_key() -> None:
    with pytest.raises(HealthDefinitionError, match="unknown health-definition key"):
        parse_definition({"stale_after_hrs": 12})


def test_parse_reads_a_full_definition() -> None:
    d = parse_definition(
        {
            "version": 2,
            "severity_map": {"critical": "critical", "warning": "watch", "info": "healthy"},
            "counted_statuses": ["open"],
            "snoozed_as": None,
            "cell_critical_share": "0.10",
            "recommendation_floor": 0.8,
            "stale_after_hours": 12,
            "no_tree_coverage": "healthy",
        }
    )
    assert d.version == 2
    assert d.counted_statuses == frozenset({"open"})
    assert d.snoozed_as is None
    assert d.cell_critical_share == Decimal("0.10")
    assert d.recommendation_floor == Decimal("0.8")
    assert d.stale_after_hours == 12
    assert d.no_tree_coverage == "healthy"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"severity_map": {"critical": "critical"}}, "must name every alert severity"),
        (
            {"severity_map": {"critical": "critical", "warning": "watch", "info": "unknown"}},
            "expected one of",
        ),
        (
            {"severity_map": {"crit": "critical", "warning": "watch", "info": "healthy"}},
            "is not an alert severity",
        ),
        ({"counted_statuses": ["open", "pending"]}, "unknown status"),
        ({"counted_statuses": ["open", "resolved"]}, "cannot include 'resolved'"),
        ({"snoozed_as": "unknown"}, "expected null or one of"),
        ({"cell_critical_share": 0}, "greater than 0 and at most 1"),
        ({"cell_critical_share": 1.5}, "greater than 0 and at most 1"),
        ({"recommendation_floor": 1.5}, "between 0 and 1"),
        ({"stale_after_hours": 0}, "must be 1 or greater"),
        ({"no_tree_coverage": "watch"}, "expected 'unknown' or 'healthy'"),
        ({"version": 0}, "version must be 1 or greater"),
        ({"stale_after_hours": "soon"}, "must be a whole number"),
        ({"severity_map": "critical"}, "must be a mapping"),
        ({"counted_statuses": "open"}, "must be a list of strings"),
        ({"counted_statuses": [1]}, "must be a list of strings"),
    ],
)
def test_parse_rejects_a_value_it_cannot_honour(raw: dict, message: str) -> None:
    with pytest.raises(HealthDefinitionError, match=message):
        parse_definition(raw)


def test_building_a_definition_directly_is_validated_too() -> None:
    """The dataclass is the same gate as the parser, not a way around it."""
    with pytest.raises(HealthDefinitionError, match="must be 1 or greater"):
        HealthDefinition(stale_after_hours=0)
