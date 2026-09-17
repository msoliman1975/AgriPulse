"""The estate report's arithmetic, over fixtures of folds.

``build_estate_report`` is pure — no session, no clock — so every number in
section 9's report can be pinned here rather than inferred from a run against
a database. Six behaviours, each of which changes what an agronomist decides:

  * The counts and the percentages, against a fold whose answer is known.
  * Every cell composing, which says the combination rules are not earning
    their place.
  * A rule that never fires, which is either wrong or unreachable.
  * A rule written without a code, which fires and must not be reported as
    never firing.
  * Errors counted separately and attributed to the node that caused them.
  * Blocks the tree does not target, kept out of every total.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.modules.recommendations.folding_engine import CombinationRule
from app.modules.recommendations.folding_report import (
    BlockFold,
    build_estate_report,
    error_node_id,
)


def _cell(
    *,
    identity: list[str] | None = None,
    composed: bool = True,
    rule_code: str | None = None,
    error: str | None = None,
    status: str = "watch",
) -> dict[str, Any]:
    """One cell row in the shape the per-block dry run returns."""
    return {
        "cell_id": uuid4(),
        "cell_row": 0,
        "cell_col": 0,
        "identity": identity or [],
        "findings": [],
        "severity": "warning" if identity else None,
        "status": status if identity else None,
        "action_type": "irrigate" if identity else None,
        "text_en": "text" if identity else None,
        "text_ar": None,
        "composed": composed,
        "rule_code": rule_code,
        "stopped_at": None if error else "n_stop",
        "error": error,
    }


def _block(cells: list[dict[str, Any]], *, targeted: bool = True, ms: float = 10.0) -> BlockFold:
    return BlockFold(
        block_id=uuid4(),
        block_name="B-01",
        farm_id=uuid4(),
        farm_name="Farm",
        targeted=targeted,
        duration_ms=ms,
        cells=tuple(cells),
    )


def test_counts_and_percentages() -> None:
    """Ten cells: seven healthy, two dry, one dry and low."""
    rules = [
        CombinationRule(codes=frozenset({"dry", "ndvi_low"}), text_en="Water first", code="r3"),
        CombinationRule(codes=frozenset({"pest_high"}), text_en="Spray", code="r9"),
    ]
    cells = [_cell() for _ in range(7)]
    cells += [_cell(identity=["dry"]) for _ in range(2)]
    cells += [_cell(identity=["dry", "ndvi_low"], composed=False, rule_code="r3")]

    report = build_estate_report(blocks=[_block(cells)], rules=rules, scope="cell", total_ms=43.0)

    assert report["cells_evaluated"] == 10
    assert report["cells_no_findings"] == 7
    assert report["cells_no_findings_pct"] == 70.0
    assert report["cells_carded"] == 3
    assert report["cells_errored"] == 0

    sets = report["finding_sets"]
    # Sorted by count, so the two dry cells come before the single pair.
    assert [s["label"] for s in sets] == ["{dry}", "{dry, ndvi_low}"]
    assert sets[0]["count"] == 2
    assert sets[0]["matched_rule"] is None
    assert sets[0]["composed"] is True
    assert sets[1]["matched_rule"] == "r3"
    assert sets[1]["composed"] is False

    assert report["rules_defined"] == 2
    assert report["rules_fired"] == 1
    assert report["rules_never_fired"] == ["r9"]
    # Two of the three carded cells composed.
    assert report["composed_share_pct"] == 66.7
    assert report["timing"]["total_ms"] == 43.0
    assert report["timing"]["per_cell_ms"] == 4.3


def test_every_cell_composes() -> None:
    """The case the design warns about: rules that never earn their place."""
    rules = [CombinationRule(codes=frozenset({"dry", "ndvi_low"}), text_en="x", code="r1")]
    cells = [_cell(identity=["dry", "ndvi_low", "pest_high"]) for _ in range(4)]

    report = build_estate_report(blocks=[_block(cells)], rules=rules, scope="cell", total_ms=8.0)

    assert report["composed_share_pct"] == 100.0
    assert report["rules_fired"] == 0
    assert report["rules_never_fired"] == ["r1"]
    assert report["finding_sets"][0]["matched_rule"] is None


def test_a_rule_without_a_code_still_counts_as_fired() -> None:
    """A rule with no id fires like any other, and this is the normal case.

    ``folding_compiler._check_combinations`` keeps codes, action_type, status
    and both texts, and drops ``code``, so no author-given rule id survives a
    publish at all. Every fired rule therefore arrives here with
    ``rule_code`` None, and counting fired rules from ``rule_code`` would
    report every rule as never firing.
    """
    rules = [CombinationRule(codes=frozenset({"dry"}), text_en="Irrigate", code=None)]
    cells = [_cell(identity=["dry"], composed=False, rule_code=None)]

    report = build_estate_report(blocks=[_block(cells)], rules=rules, scope="cell", total_ms=1.0)

    assert report["rules_fired"] == 1
    assert report["rules_never_fired"] == []
    assert report["finding_sets"][0]["matched_rule"] == "{dry}"


def test_errors_are_counted_and_named_by_node() -> None:
    """A switch on a missing index stops the walk, and the node is the answer.

    Cloud cover makes a missing index common, so this count is what says
    whether a tenant can be switched on at all.
    """
    cells = [_cell() for _ in range(2)]
    cells += [
        _cell(error="switch node 'n_soil' matched no case: indices.ndvi.mean is null")
        for _ in range(3)
    ]
    cells += [_cell(error="node 'n_water' condition must be an object")]

    report = build_estate_report(blocks=[_block(cells)], rules=[], scope="cell", total_ms=6.0)

    assert report["cells_errored"] == 4
    assert report["cells_errored_pct"] == 66.7
    assert report["errors"]["count"] == 4
    by_node = report["errors"]["by_node"]
    assert by_node[0]["node_id"] == "n_soil"
    assert by_node[0]["count"] == 3
    assert by_node[1]["node_id"] == "n_water"
    # An errored cell is not healthy and not carded. The tree never said it
    # was finished, so its findings are not a conclusion.
    assert report["cells_no_findings"] == 2
    assert report["cells_carded"] == 0


def test_blocks_the_tree_does_not_target_are_kept_out_of_every_total() -> None:
    """The sweep would never walk them, so counting them overstates the tree."""
    targeted = _block([_cell(identity=["dry"]), _cell()])
    other = _block([_cell(identity=["pest_high"]) for _ in range(5)], targeted=False)

    report = build_estate_report(blocks=[targeted, other], rules=[], scope="cell", total_ms=4.0)

    assert report["blocks_evaluated"] == 1
    assert report["blocks_not_targeted"] == 1
    assert report["cells_evaluated"] == 2
    assert [s["label"] for s in report["finding_sets"]] == ["{dry}"]


def test_a_failed_block_is_named_and_does_not_end_the_run() -> None:
    good = _block([_cell(identity=["dry"])])
    bad = BlockFold(
        block_id=uuid4(),
        block_name="B-99",
        farm_id=uuid4(),
        farm_name="Farm",
        targeted=True,
        duration_ms=2.0,
        cells=(),
        error="no grid config for this block",
    )

    report = build_estate_report(blocks=[good, bad], rules=[], scope="cell", total_ms=5.0)

    assert report["blocks_evaluated"] == 1
    assert report["blocks_failed"] == 1
    assert report["block_failures"][0]["block_name"] == "B-99"
    assert report["cells_evaluated"] == 1


def test_sets_beyond_the_cap_are_rolled_up() -> None:
    """Section 9 prints "8 other sets 43" rather than 8 more lines."""
    cells: list[dict[str, Any]] = []
    for index in range(5):
        cells += [_cell(identity=[f"code_{index}"]) for _ in range(index + 1)]

    report = build_estate_report(
        blocks=[_block(cells)], rules=[], scope="cell", total_ms=1.0, top_sets=2
    )

    assert len(report["finding_sets"]) == 2
    assert report["finding_sets"][0]["count"] == 5
    assert report["other_sets"]["sets"] == 3
    # 1 + 2 + 3 cells in the three sets that were rolled up.
    assert report["other_sets"]["cells"] == 6


def test_no_cells_at_all_divides_by_nothing() -> None:
    report = build_estate_report(blocks=[], rules=[], scope="cell", total_ms=0.0)

    assert report["cells_evaluated"] == 0
    assert report["cells_no_findings_pct"] == 0.0
    assert report["composed_share_pct"] == 0.0
    assert report["timing"]["per_cell_ms"] == 0.0


def test_error_node_id_reads_every_shape_the_walk_raises() -> None:
    assert error_node_id("unknown node id 'n_missing'") == "n_missing"
    assert error_node_id("register node 'n_dry' missing 'code'") == "n_dry"
    assert error_node_id("switch node 'n_s' case 2 missing 'go' pointer") == "n_s"
    assert error_node_id("node 'n_c' condition must be an object") == "n_c"
    # The cycle names the node holding the edge that closes it, which is the
    # node an author has to edit.
    assert error_node_id("cycle: node 'n_a' leads back to 'n_b', already visited") == "n_a"
    # A catalogue drift error names a code, not a node, and must not invent one.
    assert error_node_id("finding 'dry' is in no catalogue") is None
    assert error_node_id(None) is None


def test_per_node_timing_is_declared_unavailable_rather_than_guessed() -> None:
    """The report says what it cannot measure.

    ``walk_tree`` has no timing hook and ``_fold_one_cell`` drops the node
    path, so nothing outside those two modules can attribute time to a node.
    A number here would be a guess.
    """
    report = build_estate_report(blocks=[_block([_cell()])], rules=[], scope="cell", total_ms=1.0)

    assert report["timing"]["node_timing"]["available"] is False
    assert "walk_tree" in report["timing"]["node_timing"]["reason"]
