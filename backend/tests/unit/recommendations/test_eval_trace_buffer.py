"""Unit tests for the evaluation-trace buffer's storage grain (tenant 0062).

The uneven grain — full JSONB for fired/error/skipped, path-only for clear —
is a deliberate size trade-off documented in the migration. It is also the
kind of rule that regresses silently: nothing breaks if a `clear` row starts
carrying every resolved value, the table just quietly grows several-fold. DB-less.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.modules.recommendations.engine import EvaluationResult, TreePathStep
from app.modules.recommendations.service import TargetingVerdict, _TraceBuffer

_RUN = UUID("00000000-0000-0000-0000-0000000000a1")
_FARM = UUID("00000000-0000-0000-0000-0000000000f1")
_BLOCK = UUID("00000000-0000-0000-0000-0000000000b1")


def _tree(code: str = "demo_v1", *, scope: str = "block") -> dict[str, Any]:
    return {"tree_id": uuid4(), "tree_code": code, "version": 3, "scope": scope}


def _result(*, error: str | None = None) -> EvaluationResult:
    return EvaluationResult(
        outcome=None,
        path=[
            TreePathStep(
                node_id="root",
                matched=True,
                label_en="NDVI below baseline?",
                label_ar=None,
                condition_snapshot={"indices.ndvi.mean": "0.11"},
            ),
            TreePathStep(
                node_id="leaf_scout",
                matched=None,
                label_en="Scout it",
                label_ar=None,
                condition_snapshot=None,
            ),
        ],
        error=error,
        evaluation_snapshot={"indices.ndvi.mean": "0.11", "weather.forecast_24h.rain": None},
    )


def _buffer_one(status: str, **kw: Any) -> dict[str, Any]:
    buf = _TraceBuffer(run_id=_RUN)
    buf.add(
        tree=_tree(),
        farm_id=_FARM,
        block_id=_BLOCK,
        cell_id=None,
        status=status,
        **kw,
    )
    (row,) = buf.rows
    return row


def test_fired_row_carries_the_walk_and_every_resolved_value() -> None:
    row = _buffer_one("fired", result=_result(), outcome={"action_type": "scout"})
    assert [s["node_id"] for s in row["node_path"]] == ["root", "leaf_scout"]
    assert row["resolved_values"] == {
        "indices.ndvi.mean": "0.11",
        "weather.forecast_24h.rain": None,
    }
    assert row["outcome"] == {"action_type": "scout"}


def test_error_row_carries_the_full_payload_and_the_message() -> None:
    row = _buffer_one("error", result=_result(error="unknown node id 'typo'"))
    assert row["resolved_values"] != {}
    assert row["error"] == "unknown node id 'typo'"


def test_clear_row_keeps_the_path_but_drops_the_values() -> None:
    """The compact case, and the overwhelming majority of rows. The path still
    shows which branch the block took; the value dump is what is given up."""
    row = _buffer_one("clear", result=_result())
    assert [s["node_id"] for s in row["node_path"]] == ["root", "leaf_scout"]
    assert row["resolved_values"] == {}


def test_a_null_resolved_value_is_stored_not_omitted() -> None:
    """A ref that resolved to None is how a fail-closed miss looks. Dropping
    the key would make "no data" indistinguishable from "never referenced"."""
    row = _buffer_one("fired", result=_result())
    assert "weather.forecast_24h.rain" in row["resolved_values"]
    assert row["resolved_values"]["weather.forecast_24h.rain"] is None


def test_skipped_row_has_no_walk_and_names_the_axis() -> None:
    row = _buffer_one(
        "skipped",
        verdict=TargetingVerdict(matched=False, axis="country", required=("EG",), actual=None),
    )
    # Targeting excludes the tree before the engine sees it, so there is no
    # walk to store — the reason is the whole payload.
    assert row["node_path"] == []
    assert row["skip_axis"] == "country"
    assert row["skip_detail"] == {"required": ["EG"], "actual": None}


def test_param_overrides_ride_along_so_a_changed_threshold_is_visible() -> None:
    row = _buffer_one("fired", result=_result(), overrides={"ndvi_floor": 0.2})
    assert row["param_overrides"] == {"ndvi_floor": 0.2}


def test_cell_rows_carry_the_cell_and_the_scope() -> None:
    cell_id = uuid4()
    buf = _TraceBuffer(run_id=_RUN)
    buf.add(
        tree=_tree(scope="cell"),
        farm_id=_FARM,
        block_id=_BLOCK,
        cell_id=cell_id,
        status="clear",
        result=_result(),
    )
    (row,) = buf.rows
    assert row["cell_id"] == cell_id
    # The CHECK constraint in 0062 rejects a cell_id on a block-scoped row.
    assert row["scope"] == "cell"


def test_rows_accumulate_for_one_bulk_insert() -> None:
    buf = _TraceBuffer(run_id=_RUN)
    for _ in range(5):
        buf.add(
            tree=_tree(),
            farm_id=_FARM,
            block_id=_BLOCK,
            cell_id=None,
            status="clear",
            result=_result(),
        )
    assert len(buf.rows) == 5
    assert {r["run_id"] for r in buf.rows} == {_RUN}
