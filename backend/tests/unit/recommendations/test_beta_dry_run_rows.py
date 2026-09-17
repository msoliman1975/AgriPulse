"""One cell's fold, turned into the dry-run report's row.

The integration test cannot reach the card path: `public.decision_tree_findings`
arrives in a separate change, so on this branch the catalogue is empty and no
tree that registers anything compiles. This covers the same function with a
stub catalogue, which is what `folding_engine.FindingDef` being a Protocol is
for.

Three behaviours, and each has a way of quietly going wrong.

**An errored walk is never folded.** The tree did not say it was finished, so
its findings are not a conclusion. They are still reported — a trace without
them is harder to read — but the card is null and the cell counts as errored,
never as healthy.

**An empty finding set is an answer.** The tree ran and found nothing. That
is a healthy cell, not a missing one, and it appears in the report.

**A drifted catalogue reports on the cell, not on the request.** The compiler
checks every code at publish, so a code missing at run time means the
catalogue and the published tree have moved apart since. One missing code
must not hide the rest of the block's answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.modules.recommendations import folding_engine
from app.modules.recommendations.folding_authoring import _fold_one_cell
from app.shared.conditions.context import ConditionContext


@dataclass(frozen=True)
class _Finding:
    """A catalogue row, structurally a `folding_engine.FindingDef`."""

    code: str
    clause_en: str
    clause_ar: str | None
    name_en: str
    name_ar: str | None
    default_status: str
    source: str = "platform"


CATALOGUE = {
    "dry": _Finding(
        code="dry",
        clause_en="leaf water is low",
        clause_ar="ماء الأوراق منخفض",
        name_en="Low leaf water",
        name_ar="نقص ماء الأوراق",
        default_status="alert",
    ),
    "vigour_low": _Finding(
        code="vigour_low",
        clause_en="canopy vigour is below the band",
        clause_ar="حيوية المجموع دون النطاق",
        name_en="Low vigour",
        name_ar="حيوية منخفضة",
        default_status="issue",
    ),
}


def _tree(*, registers: list[str], broken_switch: bool = False) -> dict:
    nodes: dict = {}
    nxt = "n_stop"
    for code in reversed(registers):
        node_id = f"n_reg_{code}"
        nodes[node_id] = {"register": {"code": code, "severity": "warning"}, "next": nxt}
        nxt = node_id
    if broken_switch:
        # A switch whose subject resolves to nothing and whose only case
        # cannot match. A switch that matches no case stops the walk with an
        # error — deliberately stricter than the rest of the engine, which is
        # permissive on missing data (design section 10).
        nodes["n_switch"] = {
            "switch": {
                "on": {"source": "indices", "index_code": "never_measured", "key": "mean"},
                "cases": [{"ge": 0.5, "go": nxt}],
                "default": None,
            }
        }
        nxt = "n_switch"
    nodes["n_stop"] = {"stop": True}
    return {"shape": "folding", "root": nxt, "nodes": nodes, "parameters": {}}


def _ctx() -> ConditionContext:
    return ConditionContext.from_block_signals(block_id=str(uuid4()), latest_index_aggregates={})


def _row(tree: dict) -> dict:
    return _fold_one_cell(
        folding_engine,
        compiled=tree,
        ctx=_ctx(),
        catalogue=CATALOGUE,
        rules=[],
        cell_id=uuid4(),
        cell_row=3,
        cell_col=4,
    )


def test_a_healthy_cell_is_reported_with_an_empty_identity() -> None:
    row = _row(_tree(registers=[]))
    assert row["identity"] == []
    assert row["findings"] == []
    assert row["text_en"] is None
    assert row["error"] is None
    assert row["stopped_at"] == "n_stop"
    assert row["cell_row"] == 3
    assert row["cell_col"] == 4


def test_two_findings_compose_their_clauses() -> None:
    row = _row(_tree(registers=["dry", "vigour_low"]))
    assert row["identity"] == ["dry", "vigour_low"], "sorted, because it is the key"
    assert row["composed"] is True, "no rule matched, so the text was composed"
    assert row["rule_code"] is None
    # The composer joins the clauses and sentence-cases the result, so the
    # first clause arrives capitalised. Asserted as the whole sentence rather
    # than as two substrings, because the join and the order are the part
    # that has to be right.
    assert row["text_en"] == (
        "Leaf water is low and canopy vigour is below the band."
    ), "worst severity first, joined with 'and', one full stop"
    assert row["text_ar"] is not None
    assert "ماء الأوراق منخفض" in row["text_ar"]
    assert row["error"] is None


def test_a_matching_rule_supplies_the_text_and_the_action() -> None:
    rules = folding_engine.parse_combination_rules(
        [
            {
                "codes": ["dry", "vigour_low"],
                "action_type": "irrigate",
                "status": "stressed",
                "text_en": "Water shortage is the cause. Irrigate first.",
                "text_ar": "السبب نقص ماء. اروِ أولًا.",
                "code": "r_dry_vigour",
            }
        ]
    )
    row = _fold_one_cell(
        folding_engine,
        compiled=_tree(registers=["dry", "vigour_low"]),
        ctx=_ctx(),
        catalogue=CATALOGUE,
        rules=rules,
        cell_id=uuid4(),
        cell_row=None,
        cell_col=None,
    )
    assert row["composed"] is False
    assert row["rule_code"] == "r_dry_vigour"
    assert row["text_en"] == "Water shortage is the cause. Irrigate first."
    assert row["action_type"] == "irrigate"
    assert row["status"] == "stressed"


def test_an_errored_walk_is_not_folded() -> None:
    row = _row(_tree(registers=["dry"], broken_switch=True))
    assert row["error"] is not None
    assert row["identity"] == [], "a walk that did not finish produced no card"
    assert row["text_en"] is None
    assert row["stopped_at"] is None


def test_a_code_the_catalogue_lost_is_reported_on_the_cell() -> None:
    row = _fold_one_cell(
        folding_engine,
        compiled=_tree(registers=["dry"]),
        ctx=_ctx(),
        catalogue={},  # the catalogue drifted away from the published tree
        rules=[],
        cell_id=uuid4(),
        cell_row=0,
        cell_col=0,
    )
    assert row["error"] is not None
    assert "dry" in row["error"]
    assert row["identity"] == []
    # The findings the walk did collect are still there, because a trace
    # without them is harder to read than one with them.
    assert [f["code"] for f in row["findings"]] == ["dry"]


def test_registered_by_names_every_node_that_agreed() -> None:
    tree = _tree(registers=["dry"])
    # A second node registering the same code is one entry, not two, and the
    # trace still shows which checks agreed.
    tree["nodes"]["n_reg_dry_again"] = {
        "register": {"code": "dry", "severity": "critical"},
        "next": "n_stop",
    }
    tree["nodes"]["n_reg_dry"]["next"] = "n_reg_dry_again"
    row = _row(tree)
    assert row["identity"] == ["dry"]
    assert row["findings"][0]["registered_by"] == ["n_reg_dry", "n_reg_dry_again"]
    assert row["findings"][0]["severity"] == "critical", "the higher severity wins"
