"""The pure half of folding execution: shape, adapter, notification rule.

Everything here runs without a database. The database half — supersede across
four runs, the three parameter layers, the fold columns on a trace — is in
``tests/integration/recommendations/test_folding_execution.py``.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.recommendations.folding_engine import (
    FoldingPathStep,
    FoldingWalkResult,
    RegisteredFinding,
    fold,
)
from app.modules.recommendations.service import (
    _finding_rows_from,
    _FindingRow,
    _fold_trace_columns,
    _folding_evaluation,
    _is_folding_shape,
    _notify_on_supersede,
)

_CATALOGUE = {
    "dry": _FindingRow(
        code="dry",
        clause_en="leaf water is low",
        clause_ar=None,
        name_en="Dry",
        name_ar=None,
        default_status="alert",
        source="tree",
        action_type="irrigate",
    ),
    "ndvi_low": _FindingRow(
        code="ndvi_low",
        clause_en="canopy vigour dropped",
        clause_ar=None,
        name_en="Low vigour",
        name_ar=None,
        default_status="issue",
        source="tree",
        action_type="scout",
    ),
    "in_band": _FindingRow(
        code="in_band",
        clause_en="nitrogen is in band",
        clause_ar=None,
        name_en="In band",
        name_ar=None,
        default_status="good",
        source="tree",
        action_type="scout",
    ),
}


def _walk(*findings: RegisteredFinding) -> FoldingWalkResult:
    result = FoldingWalkResult(findings=list(findings))
    result.path = [FoldingPathStep(node_id="stop", kind="stop")]
    result.stopped_at = "stop"
    return result


# --- which engine walks a tree ----------------------------------------------


def test_a_register_node_makes_a_tree_fold() -> None:
    assert _is_folding_shape(
        {"nodes": {"r": {"register": {"code": "dry"}, "next": "s"}, "s": {"stop": True}}}
    )


def test_a_stop_node_alone_makes_a_tree_fold() -> None:
    assert _is_folding_shape({"nodes": {"s": {"stop": True}}})


def test_an_old_style_tree_does_not_fold() -> None:
    assert not _is_folding_shape(
        {
            "nodes": {
                "root": {"condition": {"tree": {}}, "on_match": "leaf", "on_miss": "leaf"},
                "leaf": {"outcome": {"action_type": "scout"}},
            }
        }
    )


def test_a_body_with_no_nodes_does_not_fold() -> None:
    assert not _is_folding_shape({})
    assert not _is_folding_shape(None)


# --- the adapter ------------------------------------------------------------


def test_an_alert_card_becomes_an_alert_outcome() -> None:
    walk = _walk(RegisteredFinding(code="dry", severity="warning", registered_by=("reg_dry",)))
    card = fold(walk.findings, catalogue=_CATALOGUE)
    assert card is not None

    result = _folding_evaluation(walk, card)

    assert result.error is None
    assert result.outcome is not None
    assert result.outcome.kind == "alert"
    # The fold's own status, not the fixed amber every card used to get.
    assert result.outcome.status_code == "alert"
    assert result.outcome.action_type == "irrigate"
    assert result.outcome.severity == "warning"
    assert result.outcome.confidence == Decimal("1")
    assert result.outcome.leaf_node_id == "stop"
    assert result.outcome.parameters["finding_set"] == ["dry"]
    assert result.outcome.parameters["health_status"] == "alert"


def test_an_issue_card_becomes_a_recommendation_outcome() -> None:
    walk = _walk(RegisteredFinding(code="ndvi_low", severity="warning", registered_by=("r",)))
    card = fold(walk.findings, catalogue=_CATALOGUE)
    assert card is not None

    result = _folding_evaluation(walk, card)

    assert result.outcome is not None
    assert result.outcome.kind == "recommendation"
    assert result.outcome.status_code == "issue"
    assert result.outcome.action_type == "scout"


def test_a_good_card_asks_for_no_work_and_keeps_its_words() -> None:
    """`no_action` is what keeps the card off the board; the text stays the
    finding's own, so the verdict says what was found and not a blank."""
    walk = _walk(RegisteredFinding(code="in_band", severity="info", registered_by=("r",)))
    card = fold(walk.findings, catalogue=_CATALOGUE)
    assert card is not None

    result = _folding_evaluation(walk, card)

    assert result.outcome is not None
    assert result.outcome.kind == "status"
    assert result.outcome.status_code == "good"
    assert result.outcome.action_type == "no_action"
    assert "nitrogen is in band" in result.outcome.text_en.lower()
    assert result.outcome.parameters["finding_set"] == ["in_band"]


def test_an_action_type_outside_the_column_becomes_other() -> None:
    """A catalogue verb the recommendations CHECK does not admit must not
    fail the insert for the whole block."""
    catalogue = {
        "odd": _FindingRow(
            code="odd",
            clause_en="something else",
            clause_ar=None,
            name_en="Odd",
            name_ar=None,
            default_status="issue",
            source="tree",
            action_type="rototill",
        )
    }
    walk = _walk(RegisteredFinding(code="odd", severity="info", registered_by=("r",)))
    card = fold(walk.findings, catalogue=catalogue)
    assert card is not None
    assert card.action_type == "rototill"

    result = _folding_evaluation(walk, card)
    assert result.outcome is not None
    assert result.outcome.action_type == "other"


def test_an_empty_set_is_a_status_outcome_not_a_missing_one() -> None:
    walk = _walk()
    result = _folding_evaluation(walk, None)

    assert result.outcome is not None
    assert result.outcome.kind == "status"
    assert result.outcome.status_code == "good"
    # `no_action` is what the service reads as "nothing opens here".
    assert result.outcome.action_type == "no_action"


def test_a_broken_walk_carries_its_error_and_no_outcome() -> None:
    walk = FoldingWalkResult()
    walk.error = "unknown node id 'nowhere'"
    result = _folding_evaluation(walk, None)

    assert result.outcome is None
    assert result.error == "unknown node id 'nowhere'"


def test_the_path_keeps_what_each_node_did() -> None:
    walk = FoldingWalkResult()
    walk.path = [
        FoldingPathStep(node_id="c", kind="condition", matched=True, condition_snapshot={"x": 1}),
        FoldingPathStep(node_id="r", kind="register", detail={"code": "dry"}),
        FoldingPathStep(node_id="stop", kind="stop"),
    ]
    walk.stopped_at = "stop"
    result = _folding_evaluation(walk, None)

    assert [s.node_id for s in result.path] == ["c", "r", "stop"]
    assert result.path[0].condition_snapshot == {"x": 1, "kind": "condition"}
    assert result.path[1].condition_snapshot == {"kind": "register", "detail": {"code": "dry"}}


# --- the trace columns ------------------------------------------------------


def test_an_old_style_walk_writes_empty_fold_columns() -> None:
    assert _fold_trace_columns(None, None) == {
        "finding_set": [],
        "matched_rule": None,
        "registered_by": {},
    }


def test_registered_by_lists_every_node_that_agreed() -> None:
    walk = _walk(
        RegisteredFinding(code="dry", severity="warning", registered_by=("reg_a", "reg_b"))
    )
    card = fold(walk.findings, catalogue=_CATALOGUE)
    columns = _fold_trace_columns(walk, card)

    assert columns["finding_set"] == ["dry"]
    assert columns["registered_by"] == {"dry": ["reg_a", "reg_b"]}


def test_a_broken_walk_still_reports_the_findings_it_had() -> None:
    walk = _walk(RegisteredFinding(code="dry", severity="warning", registered_by=("reg_a",)))
    walk.error = "cycle"
    columns = _fold_trace_columns(walk, None)

    assert columns["finding_set"] == []
    assert columns["registered_by"] == {"dry": ["reg_a"]}


# --- when a replaced card is worth a notification ---------------------------


def test_a_gained_finding_notifies() -> None:
    assert _notify_on_supersede(
        old_codes=["dry"],
        old_severity="warning",
        new_codes=["dry", "ndvi_low"],
        new_severity="critical",
    )


def test_a_risen_severity_notifies_even_with_the_same_codes() -> None:
    assert _notify_on_supersede(
        old_codes=["dry"], old_severity="warning", new_codes=["dry"], new_severity="critical"
    )


def test_a_lost_finding_is_silent() -> None:
    assert not _notify_on_supersede(
        old_codes=["dry", "ndvi_low"],
        old_severity="critical",
        new_codes=["dry"],
        new_severity="warning",
    )


def test_a_swapped_finding_notifies_because_something_is_new() -> None:
    assert _notify_on_supersede(
        old_codes=["dry"], old_severity="warning", new_codes=["ndvi_low"], new_severity="warning"
    )


def test_nothing_changed_is_silent() -> None:
    assert not _notify_on_supersede(
        old_codes=["dry"], old_severity="warning", new_codes=["dry"], new_severity="warning"
    )


# --- reading a findings block -----------------------------------------------


def test_a_findings_block_reads_as_a_map_or_a_list() -> None:
    as_map = _finding_rows_from(
        {"dry": {"clause_en": "leaf water is low", "default_status": "alert"}}, source="tree"
    )
    as_list = _finding_rows_from(
        [{"code": "dry", "clause_en": "leaf water is low", "default_status": "alert"}],
        source="tree",
    )
    assert as_map["dry"].clause_en == as_list["dry"].clause_en == "leaf water is low"
    assert as_map["dry"].default_status == "alert"
    # No name declared, so the code stands in rather than an empty header.
    assert as_map["dry"].name_en == "dry"


def test_an_entry_with_no_clause_is_dropped() -> None:
    """A finding with no clause leaves a hole in the composed sentence. It is
    dropped here so the fold raises on the code instead of printing a gap."""
    assert _finding_rows_from({"dry": {"name_en": "Dry"}}, source="tree") == {}
