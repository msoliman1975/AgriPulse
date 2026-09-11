"""Four leaf kinds, five status codes, and what an old tree compiles to.

A leaf used to be a recommendation or an alert, and a branch that found
nothing wrong said ``action_type: no_action`` and wrote no row. Nobody could
be told "this block was checked and it is fine". A leaf now declares one of
four kinds and every evaluation resolves to one of five status codes.

The two rules these tests exist for:

  * A tree published before any of this compiles unchanged, and its
    ``no_action`` branches keep meaning "nothing to say" — not "issue".
  * A typo in a status fails when the tree is published. An unknown
    condition operator once compiled, published and ran without showing any
    error for months, because the evaluator caught the parse failure and
    answered "did not match". A status must not be able to do that.

DB-less: the loader and the engine are pure functions.

See ``docs/proposals/decision-tree-status-verdicts.md``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.recommendations.engine import _parse_outcome, evaluate_tree
from app.modules.recommendations.errors import DecisionTreeParseError
from app.modules.recommendations.loader import compile_tree
from app.modules.recommendations.status_codes import (
    LEAF_KINDS,
    STATUS_BY_CODE,
    STATUS_CODES,
    STATUS_DEFINITIONS,
    rank_of,
    status_for,
    worst,
)
from app.shared.conditions import ConditionContext
from tests.support.shipped_trees import iter_shipped_yaml


def _spec(leaf: dict[str, Any]) -> dict[str, Any]:
    """A one-node tree whose root is the leaf under test."""
    return {
        "code": "probe_v1",
        "name_en": "Probe",
        "root": "leaf",
        "nodes": {"leaf": {"outcome": leaf}},
    }


def _walk(leaf: dict[str, Any]) -> Any:
    compiled = compile_tree(_spec(leaf), source_path="probe")
    return evaluate_tree(compiled, ConditionContext(block_id="b1")).outcome


# --------------------------------------------------------------------------
# The list itself
# --------------------------------------------------------------------------


def test_the_five_codes_and_their_colours() -> None:
    assert STATUS_CODES == ("na", "very_good", "good", "issue", "alert")
    assert [d.color for d in STATUS_DEFINITIONS] == [
        "#9AA0A6",
        "#1B873F",
        "#6FBF4B",
        "#E8A33D",
        "#D64545",
    ]


def test_every_code_carries_both_languages() -> None:
    for definition in STATUS_DEFINITIONS:
        assert definition.label_en
        assert definition.label_ar
        # An Arabic label that is still the English one is the failure this
        # catches: 1656 green tests once shipped English under Arabic names.
        assert definition.label_ar != definition.label_en


def test_na_never_outranks_a_real_answer() -> None:
    assert rank_of("na") == 0
    for code in ("very_good", "good", "issue", "alert"):
        assert rank_of(code) > rank_of("na")
    assert worst(["na", "very_good"]) == "very_good"


def test_worst_wins_over_a_block_s_verdicts() -> None:
    assert worst(["good", "issue", "very_good"]) == "issue"
    assert worst(["good", "alert", "issue"]) == "alert"
    assert worst(["good", "good"]) == "good"
    assert worst([]) is None


def test_an_unknown_code_ranks_last_and_does_not_raise() -> None:
    # A rollup over a whole farm must not fail on one hand-edited row.
    assert rank_of("purple") == -1
    assert worst(["purple", "na"]) == "na"


def test_a_kind_that_asks_for_work_cannot_choose_its_own_colour() -> None:
    assert status_for("alert", "good") == "alert"
    assert status_for("recommendation", "very_good") == "issue"
    assert status_for("no_action", "good") == "na"
    assert status_for("status", "very_good") == "very_good"
    # An unknown status on a status leaf falls back rather than raising;
    # the loader already refused to publish it.
    assert status_for("status", "purple") == "good"


def test_the_four_kinds() -> None:
    assert set(LEAF_KINDS) == {"alert", "recommendation", "status", "no_action"}


# --------------------------------------------------------------------------
# Compiling and walking a leaf
# --------------------------------------------------------------------------


def test_a_status_leaf_needs_no_action_type() -> None:
    outcome = _walk({"kind": "status", "status": "very_good", "text_en": "Canopy is dense."})

    assert outcome is not None
    assert outcome.kind == "status"
    assert outcome.status_code == "very_good"
    assert outcome.text_en == "Canopy is dense."


def test_an_old_no_action_leaf_still_compiles_and_means_nothing_to_say() -> None:
    # No `kind` at all — how all 63 shipped no_action leaves are written.
    outcome = _walk({"action_type": "no_action", "text_en": "No action needed."})

    assert outcome is not None
    assert outcome.kind == "no_action"
    assert outcome.status_code == "na"


def test_an_old_recommendation_leaf_is_unchanged() -> None:
    outcome = _walk({"action_type": "irrigate", "text_en": "Irrigate.", "confidence": 0.7})

    assert outcome is not None
    assert outcome.kind == "recommendation"
    assert outcome.status_code == "issue"
    assert outcome.action_type == "irrigate"


def test_an_alert_leaf_is_unchanged_and_paints_alert() -> None:
    outcome = _walk(
        {
            "kind": "alert",
            "action_type": "scout",
            "severity": "critical",
            "text_en": "Fruit fly pressure.",
        }
    )

    assert outcome is not None
    assert outcome.status_code == "alert"
    assert outcome.severity == "critical"


# --------------------------------------------------------------------------
# What the loader refuses to publish
# --------------------------------------------------------------------------


def test_an_unknown_status_is_refused_at_publish_time() -> None:
    with pytest.raises(DecisionTreeParseError) as err:
        compile_tree(
            _spec({"kind": "status", "status": "gud", "text_en": "ok"}),
            source_path="probe",
        )

    assert "'outcome.status'" in err.value.detail
    assert "gud" in err.value.detail


def test_an_unknown_kind_is_refused_at_publish_time() -> None:
    with pytest.raises(DecisionTreeParseError) as err:
        compile_tree(
            _spec({"kind": "verdict", "action_type": "scout", "text_en": "ok"}),
            source_path="probe",
        )

    assert "'outcome.kind'" in err.value.detail


def test_only_a_status_leaf_may_name_a_status() -> None:
    # An alert leaf that named `good` would paint green while opening a red
    # card, so this is an error and not a value we quietly drop.
    with pytest.raises(DecisionTreeParseError) as err:
        compile_tree(
            _spec(
                {
                    "kind": "alert",
                    "action_type": "scout",
                    "severity": "warning",
                    "status": "good",
                    "text_en": "ok",
                }
            ),
            source_path="probe",
        )

    assert "Only a 'status' leaf" in err.value.detail


def test_a_recommendation_leaf_still_needs_an_action_type() -> None:
    with pytest.raises(DecisionTreeParseError) as err:
        compile_tree(_spec({"kind": "recommendation", "text_en": "ok"}), source_path="probe")

    assert "'outcome.action_type'" in err.value.detail


def test_every_shipped_status_code_compiles() -> None:
    for code in STATUS_CODES:
        outcome = _walk({"kind": "status", "status": code, "text_en": "ok"})
        assert outcome is not None
        assert outcome.status_code == code
        assert STATUS_BY_CODE[code].color.startswith("#")


def test_a_recommendation_of_no_action_is_not_a_recommendation() -> None:
    """15 of the 63 shipped no-action leaves are written this way.

    They say ``kind: recommendation`` and ``action_type: no_action`` in the
    same outcome, and their text reads "within the sufficiency band" or "no
    reading has been ingested". Reading the declared kind would paint all 15
    amber, which is the opposite of what they say.
    """
    outcome = _walk(
        {
            "kind": "recommendation",
            "action_type": "no_action",
            "severity": "info",
            "text_en": "Petiole sap nitrate is within the sufficiency band.",
        }
    )

    assert outcome is not None
    assert outcome.kind == "no_action"
    assert outcome.status_code == "na"


def test_every_shipped_seed_leaf_resolves_to_a_known_status() -> None:
    """All 33 seed files compile, and no leaf lands on an unknown status.

    Counted after the rewrite on 2026-09-07: 5 alert leaves, 83
    recommendation leaves, and the 63 that used to be no-action leaves now
    split 30 `good` and 33 `na`. Not one no-action leaf is left, which is
    the point: a branch that found nothing wrong now says so.
    """
    import collections

    import yaml

    counts: collections.Counter[str] = collections.Counter()
    for name, raw in iter_shipped_yaml():
        compiled = compile_tree(yaml.safe_load(raw), source_path=name)
        for nid, node in compiled["nodes"].items():
            if "outcome" not in node:
                continue
            outcome = _parse_outcome(node["outcome"], leaf_node_id=nid, params={})
            assert outcome is not None, f"{name}:{nid} did not parse"
            assert outcome.status_code in STATUS_CODES
            counts[outcome.kind] += 1
            if outcome.kind == "status":
                counts[f"status:{outcome.status_code}"] += 1
                # A status leaf's whole job is to say something. One with no
                # words is the blank row again, wearing a colour.
                assert outcome.text_en, f"{name}:{nid} has no English text"
                assert outcome.text_ar, f"{name}:{nid} has no Arabic text"

    assert counts["no_action"] == 0
    assert counts["alert"] == 5
    assert counts["recommendation"] == 83
    assert counts["status"] == 63
    assert counts["status:good"] == 30
    assert counts["status:na"] == 33
