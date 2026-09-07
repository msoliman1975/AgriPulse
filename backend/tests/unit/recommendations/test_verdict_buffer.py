"""What the sweep collects before it writes a block's verdicts.

The buffer is the part of the write path that needs no database: it decides
what each leaf turns into, and it remembers what the pass produced so the
rows it did NOT produce can be closed afterwards. That second job is the one
a loop over the results cannot do, and it is what stops a block keeping a
green verdict from a tree that no longer runs on it.

The SQL half is checked separately, against a real database.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.recommendations.engine import TreeOutcome
from app.modules.recommendations.service import _VerdictBuffer

_FARM = uuid4()
_BLOCK = uuid4()


def _tree(tree_id: UUID | None = None, code: str = "demo_v1") -> dict:
    return {"tree_id": tree_id or uuid4(), "tree_code": code, "version": 3}


def _outcome(**kw) -> TreeOutcome:
    base = {
        "action_type": "no_action",
        "severity": "info",
        "confidence": Decimal("0.5"),
        "parameters": {},
        "text_en": "Checked and fine.",
        "text_ar": "تم الفحص.",
        "valid_for_hours": None,
        "kind": "status",
        "status_code": "good",
        "leaf_node_id": "leaf_ok",
    }
    base.update(kw)
    return TreeOutcome(**base)


def _add(buffer: _VerdictBuffer, tree: dict, outcome: TreeOutcome, cell_id: UUID | None = None):
    buffer.add(
        tree=tree,
        farm_id=_FARM,
        block_id=_BLOCK,
        cell_id=cell_id,
        outcome=outcome,
    )


def test_a_status_leaf_becomes_a_block_scoped_row() -> None:
    buffer = _VerdictBuffer()
    tree = _tree()

    _add(buffer, tree, _outcome())

    (row,) = buffer.rows
    assert row["scope"] == "block"
    assert row["cell_id"] is None
    assert row["kind"] == "status"
    assert row["status_code"] == "good"
    assert row["text_ar"] == "تم الفحص."
    assert row["tree_version"] == 3


def test_a_status_row_carries_no_severity() -> None:
    """The table's CHECK refuses it, and the status already ranks the row.

    The outcome object still holds a severity, because every leaf kind shares
    one shape, so dropping it has to happen here.
    """
    buffer = _VerdictBuffer()

    _add(buffer, _tree(), _outcome(severity="critical"))

    assert buffer.rows[0]["severity"] is None


def test_a_no_action_leaf_becomes_na() -> None:
    buffer = _VerdictBuffer()

    _add(buffer, _tree(), _outcome(kind="no_action", status_code="na"))

    assert buffer.rows[0]["status_code"] == "na"
    assert buffer.rows[0]["severity"] is None


def test_an_alert_leaf_keeps_its_severity_and_its_item() -> None:
    buffer = _VerdictBuffer()
    alert_id = uuid4()

    buffer.add(
        tree=_tree(),
        farm_id=_FARM,
        block_id=_BLOCK,
        cell_id=None,
        outcome=_outcome(kind="alert", status_code="alert", severity="critical"),
        alert_id=alert_id,
    )

    row = buffer.rows[0]
    assert row["severity"] == "critical"
    assert row["alert_id"] == alert_id
    assert row["recommendation_id"] is None


def test_a_cell_verdict_is_cell_scoped() -> None:
    buffer = _VerdictBuffer()
    cell_id = uuid4()

    _add(buffer, _tree(), _outcome(), cell_id=cell_id)

    assert buffer.rows[0]["scope"] == "cell"
    assert buffer.rows[0]["cell_id"] == cell_id


def test_the_buffer_remembers_which_trees_spoke() -> None:
    """The close-absent pass reads this, and only this.

    A tree that produced no verdict — excluded by targeting, turned off for
    the farm, archived, or erroring — is absent from the set, and its open
    rows are ended. That is invisible to a loop over the rows produced.
    """
    buffer = _VerdictBuffer()
    ran, silent = _tree(), _tree(code="quiet_v1")

    _add(buffer, ran, _outcome())

    assert buffer.seen_trees == {ran["tree_id"]}
    assert silent["tree_id"] not in buffer.seen_trees


def test_the_buffer_remembers_which_cells_each_tree_reached() -> None:
    buffer = _VerdictBuffer()
    tree = _tree()
    reached = [uuid4(), uuid4()]

    for cell_id in reached:
        _add(buffer, tree, _outcome(), cell_id=cell_id)
    _add(buffer, tree, _outcome())

    # The block-scoped row does not join the cell list; closing stale cells
    # must not treat "the block itself" as a cell that went missing.
    assert buffer.seen_cells[tree["tree_id"]] == reached


def test_a_leaf_with_no_node_id_still_writes_a_row() -> None:
    """`leaf_node_id` is NOT NULL in the table.

    The engine leaves it None only for a compiled tree edited by hand, and a
    verdict that cannot be stored at all would take the whole block's write
    down with it.
    """
    buffer = _VerdictBuffer()

    _add(buffer, _tree(), _outcome(leaf_node_id=None))

    assert buffer.rows[0]["leaf_node_id"] == ""
