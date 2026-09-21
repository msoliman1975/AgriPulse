"""The parts the walk explainer needs, without a database.

Three things are under test here:

  * the compiler carries a combination rule's own ``code``, which it used to
    drop, so no trace, dry run row or report could ever name the rule that
    wrote a card;
  * ``folding_engine.explain_card`` re-derives the working behind a card and
    agrees with the card it was given;
  * ``folding_authoring._walk_one_cell`` hands back the walk and the card
    alongside the report row, and ``_serialize_walk_path`` turns the walk into
    the response's step shape.

No evaluation context is built here. The two authoring helpers are pure
functions over a compiled body, so a fake engine module is enough to prove the
wiring; the real engine's behaviour is covered by ``test_folding_engine.py``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.recommendations.folding_authoring import (
    _fold_one_cell,
    _serialize_walk_path,
    _walk_one_cell,
)
from app.modules.recommendations.folding_compiler import (
    CompileError,
    FoldingCompileError,
    check_folding_tree,
    compile_folding_tree,
)
from app.modules.recommendations.folding_engine import (
    CombinationRule,
    FoldedCard,
    FoldingPathStep,
    FoldingWalkResult,
    RegisteredFinding,
    explain_card,
)

KNOWN = ("dry", "ndvi_low")


def _errors(spec: dict[str, Any]) -> list[CompileError]:
    return check_folding_tree(spec, known_codes=KNOWN)


def _by_rule(errors: list[CompileError], rule: str) -> list[CompileError]:
    return [e for e in errors if e.rule == rule]


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "code": "tiny",
        "name_en": "Tiny",
        "registers": ["dry", "ndvi_low"],
        "root": "root",
        "nodes": {
            "root": {"register": {"code": "dry", "severity": "warning"}, "next": "end"},
            "end": {"stop": True},
        },
    }
    spec.update(overrides)
    return spec


# --- the compiler keeps the rule's name ------------------------------------


def test_a_combination_rule_keeps_its_code_through_the_compiler() -> None:
    """The defect this change exists to fix.

    ``_check_combinations`` normalised every rule without copying ``code``,
    so ``CombinationRule.code`` was always None, ``FoldedCard.rule_code`` was
    always None, and ``decision_tree_eval_traces.matched_rule`` was null on
    every row the folding engine has ever written.
    """
    spec = _spec(
        combinations=[{"code": "dry_only", "codes": ["dry"], "text_en": "Water it."}],
    )
    compiled = compile_folding_tree(spec, known_codes=KNOWN)
    assert compiled["combinations"][0]["code"] == "dry_only"


def test_a_rule_without_a_code_is_allowed_and_comes_back_null() -> None:
    spec = _spec(combinations=[{"codes": ["dry"], "text_en": "Water it."}])
    assert _errors(spec) == []
    compiled = compile_folding_tree(spec, known_codes=KNOWN)
    assert compiled["combinations"][0]["code"] is None


def test_rejects_two_rules_that_use_the_same_code() -> None:
    spec = _spec(
        combinations=[
            {"code": "same", "codes": ["dry"], "text_en": "One."},
            {"code": "same", "codes": ["ndvi_low"], "text_en": "Two."},
        ],
    )
    errors = _by_rule(_errors(spec), "combination-duplicate-code")
    assert len(errors) == 1
    assert "'same'" in errors[0].message_en


def test_rejects_a_code_that_is_not_a_non_empty_string() -> None:
    spec = _spec(combinations=[{"code": "   ", "codes": ["dry"], "text_en": "One."}])
    assert len(_by_rule(_errors(spec), "combination-bad-code")) == 1


def test_a_code_of_the_wrong_type_is_refused_at_publish() -> None:
    """Refused, not dropped.

    Every other rule in the combinations block is a publish-time rejection,
    and a name the author typed and cannot see again is worse than being told
    to fix it.
    """
    spec = _spec(combinations=[{"code": 7, "codes": ["dry"], "text_en": "Water it."}])
    errors = _by_rule(_errors(spec), "combination-bad-code")
    assert len(errors) == 1
    assert "number 0" in errors[0].message_en
    with pytest.raises(FoldingCompileError):
        compile_folding_tree(spec, known_codes=KNOWN)


# --- explain_card ----------------------------------------------------------


class _Finding:
    """One catalogue row, as the fold reads it."""

    def __init__(self, code: str, clause_en: str, clause_ar: str | None = None) -> None:
        self.code = code
        self.clause_en = clause_en
        self.clause_ar = clause_ar
        self.name_en = code
        self.name_ar = None
        self.default_status = "issue"


CATALOGUE = {
    "dry": _Finding("dry", "soil moisture is low", "رطوبة التربة منخفضة"),
    "ndvi_low": _Finding("ndvi_low", "vigour has dropped", "انخفضت الحيوية"),
}

RULES = [
    CombinationRule(
        codes=frozenset({"dry", "ndvi_low"}),
        text_en="Water it now.",
        text_ar="اسقها الآن.",
        action_type="irrigate",
        status="alert",
        code="dry_and_weak",
    )
]


def _card(*, identity: tuple[str, ...], composed: bool) -> FoldedCard:
    return FoldedCard(
        identity=identity,
        severity="warning",
        status="issue",
        action_type="irrigate",
        text_en="whatever",
        text_ar=None,
        findings=tuple(
            RegisteredFinding(code=code, severity="warning", registered_by=("n1",))
            for code in identity
        ),
        composed=composed,
    )


def test_explain_card_names_the_rule_that_matched() -> None:
    card = _card(identity=("dry", "ndvi_low"), composed=False)
    explanation = explain_card(card, catalogue=CATALOGUE, rules=RULES)
    assert explanation.rule is not None
    assert explanation.rule.code == "dry_and_weak"
    assert explanation.clauses == ()


def test_explain_card_lists_the_clauses_composition_joined() -> None:
    card = _card(identity=("dry", "ndvi_low"), composed=True)
    explanation = explain_card(card, catalogue=CATALOGUE, rules=RULES)
    assert explanation.rule is None
    assert [c.code for c in explanation.clauses] == ["dry", "ndvi_low"]
    assert explanation.clauses[0].clause_en == "soil moisture is low"
    assert explanation.clauses[0].clause_ar == "رطوبة التربة منخفضة"


def test_explain_card_orders_the_clauses_worst_first() -> None:
    """The same order ``_compose_text`` joined them in.

    A clause list in a different order from the sentence it explains would
    read as a second, disagreeing answer.
    """
    card = FoldedCard(
        identity=("dry", "ndvi_low"),
        severity="critical",
        status="alert",
        action_type="irrigate",
        text_en="whatever",
        text_ar=None,
        findings=(
            RegisteredFinding(code="dry", severity="info", registered_by=("n1",)),
            RegisteredFinding(code="ndvi_low", severity="critical", registered_by=("n2",)),
        ),
        composed=True,
    )
    explanation = explain_card(card, catalogue=CATALOGUE, rules=RULES)
    assert [c.code for c in explanation.clauses] == ["ndvi_low", "dry"]


def test_explain_card_skips_a_finding_the_catalogue_no_longer_has() -> None:
    card = _card(identity=("dry", "gone"), composed=True)
    explanation = explain_card(card, catalogue=CATALOGUE, rules=RULES)
    assert [c.code for c in explanation.clauses] == ["dry"]


def test_explain_card_finds_no_rule_when_no_set_matches() -> None:
    card = _card(identity=("dry",), composed=False)
    assert explain_card(card, catalogue=CATALOGUE, rules=RULES).rule is None


# --- the walk survives the fold --------------------------------------------


class _FakeEngine:
    """Just enough of ``folding_engine`` for the two authoring helpers."""

    UnknownFindingError = RuntimeError

    def __init__(self, walk: FoldingWalkResult, card: FoldedCard | None) -> None:
        self._walk = walk
        self._card = card

    def walk_tree(self, compiled: Any, ctx: Any) -> FoldingWalkResult:
        return self._walk

    def fold(self, findings: Any, *, catalogue: Any, rules: Any) -> FoldedCard | None:
        return self._card


def _walk() -> FoldingWalkResult:
    return FoldingWalkResult(
        findings=[RegisteredFinding(code="dry", severity="warning", registered_by=("n2",))],
        path=[
            FoldingPathStep(
                node_id="n1",
                kind="condition",
                matched=True,
                label_en="Is the soil dry?",
                condition_snapshot={"indices.smi.mean": 0.12},
            ),
            FoldingPathStep(
                node_id="n2",
                kind="register",
                detail={"code": "dry", "severity": "warning", "repeat": False, "raised": False},
            ),
            FoldingPathStep(node_id="end", kind="stop"),
        ],
        stopped_at="end",
    )


def _call(walk: FoldingWalkResult, card: FoldedCard | None) -> tuple[dict[str, Any], Any, Any]:
    return _walk_one_cell(
        _FakeEngine(walk, card),
        compiled={},
        ctx=None,
        catalogue=CATALOGUE,
        rules=RULES,
        cell_id=uuid4(),
        cell_row=3,
        cell_col=4,
    )


def test_walk_one_cell_returns_the_walk_and_the_card_beside_the_row() -> None:
    """The dropped field this whole change turns on.

    ``_fold_one_cell`` read the findings, the stop node and the error, and
    never read ``walk.path``, so the dry run had no path to send and the
    estate report said per-node timing was unmeasurable.
    """
    card = _card(identity=("dry",), composed=True)
    row, walk, returned = _call(_walk(), card)
    assert row["identity"] == ["dry"]
    assert [step.node_id for step in walk.path] == ["n1", "n2", "end"]
    assert returned is card


def test_walk_one_cell_returns_the_walk_when_the_walk_errored() -> None:
    """A failed walk is exactly when the path is worth most.

    The card is null, because the tree never said it was finished, but the
    steps up to the failure are what tell the author where it fell over.
    """
    broken = FoldingWalkResult(
        path=[FoldingPathStep(node_id="n1", kind="condition", matched=False)],
        error="unknown node id 'nowhere'",
    )
    row, walk, card = _call(broken, None)
    assert card is None
    assert row["error"] == "unknown node id 'nowhere'"
    assert [step.node_id for step in walk.path] == ["n1"]


def test_fold_one_cell_still_returns_only_the_row() -> None:
    """The dry run's own call is unchanged."""
    row = _fold_one_cell(
        _FakeEngine(_walk(), _card(identity=("dry",), composed=True)),
        compiled={},
        ctx=None,
        catalogue=CATALOGUE,
        rules=RULES,
        cell_id=uuid4(),
        cell_row=3,
        cell_col=4,
    )
    assert isinstance(row, dict)
    assert row["cell_row"] == 3


def test_serialize_walk_path_gives_kind_and_detail_their_own_fields() -> None:
    """A stored trace row packs both inside the step's values map.

    That column is free-form JSONB and had nowhere else to put them. This
    response has somewhere, so the browser does not have to unpack anything.
    """
    steps = _serialize_walk_path(_walk())
    assert [s["node_id"] for s in steps] == ["n1", "n2", "end"]
    assert steps[0]["kind"] == "condition"
    assert steps[0]["matched"] is True
    assert steps[0]["values"] == {"indices.smi.mean": 0.12}
    assert steps[0]["detail"] is None
    assert steps[1]["kind"] == "register"
    assert steps[1]["matched"] is None
    assert steps[1]["detail"]["code"] == "dry"
    assert steps[2]["kind"] == "stop"
