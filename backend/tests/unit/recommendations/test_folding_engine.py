"""Unit tests for the folding walk and the fold. No database.

The cases here are the ones the design calls out as the ones that go wrong:
composition rather than an exact rule, a repeat register, a switch on a value
that was never read, a real cycle, and a long honest walk that the old step cap
would have cut in half.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.modules.recommendations import engine as leaf_engine
from app.modules.recommendations.folding_engine import (
    CombinationRule,
    RegisteredFinding,
    UnknownFindingError,
    fold,
    parse_combination_rules,
    walk_tree,
)
from app.shared.conditions import ConditionContext, WeatherRiskEntry
from app.shared.conditions.context import IndicesEntry
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import FindingsValueRef, VarsValueRef, parse_value_ref


@dataclass(frozen=True)
class Def:
    """Stand-in for one finding catalogue row.

    The catalogue module lands in a separate change; this carries the same
    attribute names the fold reads.
    """

    code: str
    clause_en: str
    clause_ar: str | None
    name_en: str
    name_ar: str | None
    default_status: str
    source: str
    action_type: str | None = None
    actions: dict[str, list[dict[str, Any]]] | None = None


CATALOGUE: dict[str, Def] = {
    "dry": Def(
        code="dry",
        clause_en="leaf water is low",
        clause_ar="ماء الورقة منخفض",
        name_en="Water shortage",
        name_ar="نقص الري",
        default_status="stressed",
        source="water_balance",
        action_type="irrigate",
        actions={"immediate": [{"text_en": "Irrigate this block", "text_ar": "اسقِ هذه القطعة"}]},
    ),
    "ndvi_low": Def(
        code="ndvi_low",
        clause_en="canopy vigour dropped",
        clause_ar="تراجعت حيوية المجموع الخضري",
        name_en="Vigour drop",
        name_ar="تراجع الحيوية",
        default_status="watch",
        source="indices",
        action_type="scout",
        actions={
            "monitoring": [{"text_en": "Re-read NDVI next pass", "text_ar": "أعد قراءة NDVI"}]
        },
    ),
    "pest_high": Def(
        code="pest_high",
        clause_en="anthracnose pressure is 78 out of 100",
        clause_ar="ضغط الأنثراكنوز 78 من 100",
        name_en="Anthracnose pressure",
        name_ar="ضغط الأنثراكنوز",
        default_status="stressed",
        source="weather_risk",
        action_type="spray",
        actions={
            "short_term": [{"text_en": "Plan a protectant spray", "text_ar": "خطّط لرشة وقائية"}],
            "immediate": [{"text_en": "Irrigate this block", "text_ar": "اسقِ هذه القطعة"}],
        },
    ),
    "no_arabic": Def(
        code="no_arabic",
        clause_en="the trap count rose",
        clause_ar=None,
        name_en="Trap count",
        name_ar=None,
        default_status="watch",
        source="signals",
    ),
}


def _ctx(**kwargs: Any) -> ConditionContext:
    return ConditionContext(block_id="b1", **kwargs)


def _reg(code: str, severity: str, *nodes: str) -> RegisteredFinding:
    return RegisteredFinding(code=code, severity=severity, registered_by=nodes or ("n",))


# --- the two new condition sources ------------------------------------------


def test_findings_and_vars_parse_like_every_other_source() -> None:
    assert parse_value_ref({"source": "findings", "code": "dry"}) == FindingsValueRef(
        source="findings", code="dry", key="registered"
    )
    assert parse_value_ref({"source": "vars", "name": "index_used"}) == VarsValueRef(
        source="vars", name="index_used"
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"source": "findings"},
        {"source": "findings", "code": "dry", "key": "severity"},
        {"source": "vars"},
        {"source": "vars", "name": ""},
        {"source": "not_a_source", "name": "x"},
    ],
)
def test_bad_new_source_refs_fail_the_way_an_unknown_source_does(raw: dict[str, Any]) -> None:
    with pytest.raises(ConditionParseError):
        parse_value_ref(raw)


def test_action_horizons_match_the_leaf_engine() -> None:
    from app.modules.recommendations.folding_engine import _ACTION_HORIZONS

    assert _ACTION_HORIZONS == leaf_engine._ACTION_HORIZONS


# --- the walk ---------------------------------------------------------------


def test_register_set_and_stop_collect_findings_and_variables() -> None:
    compiled = {
        "root": "n_pick",
        "nodes": {
            "n_pick": {
                "set": {
                    "index_used": "savi",
                    "ndvi_now": {"source": "indices", "index_code": "ndvi", "key": "mean"},
                },
                "next": "n_dry",
            },
            "n_dry": {"register": {"code": "dry", "severity": "warning"}, "next": "n_ask"},
            "n_ask": {
                "condition": {
                    "tree": {
                        "op": "eq",
                        "left": {"source": "vars", "name": "index_used"},
                        "right": "savi",
                    }
                },
                "on_match": "n_pest",
                "on_miss": "n_end",
            },
            "n_pest": {"register": {"code": "pest_high", "severity": "critical"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }
    ctx = _ctx(
        indices={
            "ndvi": IndicesEntry(
                time=datetime(2026, 9, 1), mean=Decimal("0.41"), baseline_deviation=None
            )
        }
    )

    result = walk_tree(compiled, ctx)

    assert result.ok
    assert result.stopped_at == "n_end"
    assert result.variables == {"index_used": "savi", "ndvi_now": Decimal("0.41")}
    assert [(f.code, f.severity) for f in result.findings] == [
        ("dry", "warning"),
        ("pest_high", "critical"),
    ]
    assert [step.kind for step in result.path] == [
        "set",
        "register",
        "condition",
        "register",
        "stop",
    ]


def test_a_findings_condition_reads_presence_and_branches_both_ways() -> None:
    compiled = {
        "root": "n_dry",
        "nodes": {
            "n_dry": {"register": {"code": "dry", "severity": "warning"}, "next": "n_ask"},
            "n_ask": {
                "condition": {
                    "tree": {
                        "all_of": [
                            {
                                "op": "eq",
                                "left": {"source": "findings", "code": "dry"},
                                "right": True,
                            },
                            {
                                "op": "eq",
                                "left": {"source": "findings", "code": "pest_high"},
                                "right": False,
                            },
                        ]
                    }
                },
                "on_match": "n_only_water",
                "on_miss": "n_end",
            },
            "n_only_water": {
                "register": {"code": "ndvi_low", "severity": "info"},
                "next": "n_end",
            },
            "n_end": {"stop": True},
        },
    }

    result = walk_tree(compiled, _ctx())

    assert result.ok
    assert sorted(f.code for f in result.findings) == ["dry", "ndvi_low"]


def test_repeat_register_is_one_entry_and_severity_only_rises() -> None:
    compiled = {
        "root": "n_a",
        "nodes": {
            "n_a": {"register": {"code": "dry", "severity": "warning"}, "next": "n_b"},
            "n_b": {"register": {"code": "dry", "severity": "critical"}, "next": "n_c"},
            "n_c": {"register": {"code": "dry", "severity": "info"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }

    result = walk_tree(compiled, _ctx())

    assert result.ok
    assert len(result.findings) == 1
    entry = result.findings[0]
    assert entry.code == "dry"
    assert entry.severity == "critical"
    assert entry.registered_by == ("n_a", "n_b", "n_c")


def test_switch_takes_the_first_matching_case() -> None:
    compiled = {
        "root": "n_pest",
        "nodes": {
            "n_pest": {
                "switch": {
                    "on": {"source": "weather_risk", "risk_code": "anthracnose", "field": "score"},
                    "cases": [{"ge": 70, "go": "n_high"}, {"ge": 40, "go": "n_med"}],
                    "default": "n_end",
                },
            },
            "n_high": {"register": {"code": "pest_high", "severity": "critical"}, "next": "n_end"},
            "n_med": {"register": {"code": "pest_high", "severity": "warning"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }
    ctx = _ctx(
        weather_risks={
            "anthracnose": WeatherRiskEntry(date=date(2026, 9, 1), score=78, level="high")
        }
    )

    result = walk_tree(compiled, ctx)

    assert result.ok
    assert [(f.code, f.severity) for f in result.findings] == [("pest_high", "critical")]
    switch_step = result.path[0]
    assert switch_step.detail == {"case": 0, "went_to": "n_high"}


def test_switch_falls_to_the_default_when_the_value_is_read_but_low() -> None:
    compiled = {
        "root": "n_pest",
        "nodes": {
            "n_pest": {
                "switch": {
                    "on": {"source": "weather_risk", "risk_code": "anthracnose", "field": "score"},
                    "cases": [{"ge": 70, "go": "n_high"}],
                    "default": "n_end",
                },
            },
            "n_high": {"register": {"code": "pest_high", "severity": "critical"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }
    ctx = _ctx(
        weather_risks={
            "anthracnose": WeatherRiskEntry(date=date(2026, 9, 1), score=12, level="low")
        }
    )

    result = walk_tree(compiled, ctx)

    assert result.ok
    assert result.findings == []
    assert result.path[0].detail == {"case": None, "went_to": "n_end"}


def test_switch_that_matches_nothing_ends_the_walk_with_an_error() -> None:
    compiled = {
        "root": "n_pest",
        "nodes": {
            "n_pest": {
                "switch": {
                    "on": {"source": "weather_risk", "risk_code": "anthracnose", "field": "score"},
                    "cases": [{"ge": 70, "go": "n_high"}],
                    "default": "n_end",
                },
            },
            "n_high": {"register": {"code": "pest_high", "severity": "critical"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }

    # No weather_risks loaded at all, so the subject value was never read. A
    # plain condition would branch to on_miss here; a switch must not reach the
    # default, because the default is for values it could compare.
    result = walk_tree(compiled, _ctx())

    assert not result.ok
    assert result.stopped_at is None
    assert result.error is not None
    assert "n_pest" in result.error
    assert "matched no case" in result.error


def test_a_revisited_node_is_a_cycle_and_names_both_ends() -> None:
    compiled = {
        "root": "n_a",
        "nodes": {
            "n_a": {"register": {"code": "dry", "severity": "info"}, "next": "n_b"},
            "n_b": {"register": {"code": "ndvi_low", "severity": "info"}, "next": "n_c"},
            "n_c": {"register": {"code": "pest_high", "severity": "info"}, "next": "n_a"},
        },
    }

    result = walk_tree(compiled, _ctx())

    assert not result.ok
    assert result.error is not None
    assert "cycle" in result.error
    assert "'n_c'" in result.error
    assert "'n_a'" in result.error


def test_two_hundred_honest_steps_finish() -> None:
    """The old engine cut every walk at 64 steps. A merged tree is a long
    sequence of independent checks, so length is not evidence of a cycle."""
    nodes: dict[str, Any] = {}
    for i in range(200):
        nodes[f"n{i}"] = {
            "condition": {
                "tree": {
                    "op": "gt",
                    "left": {"source": "indices", "index_code": "ndvi", "key": "mean"},
                    "right": 0,
                }
            },
            "on_match": f"n{i + 1}" if i < 199 else "n_end",
            "on_miss": "n_end",
        }
    nodes["n_end"] = {"stop": True}
    compiled = {"root": "n0", "nodes": nodes}
    ctx = _ctx(
        indices={
            "ndvi": IndicesEntry(
                time=datetime(2026, 9, 1), mean=Decimal("0.5"), baseline_deviation=None
            )
        }
    )

    result = walk_tree(compiled, ctx)

    assert result.ok, result.error
    assert result.stopped_at == "n_end"
    assert len(result.path) == 201


def test_an_old_style_outcome_leaf_is_refused() -> None:
    compiled = {
        "root": "n_leaf",
        "nodes": {"n_leaf": {"outcome": {"action_type": "scout", "text_en": "look"}}},
    }

    result = walk_tree(compiled, _ctx())

    assert not result.ok
    assert result.error is not None
    assert "outcome leaf" in result.error


def test_a_register_node_without_next_is_an_error() -> None:
    compiled = {
        "root": "n_a",
        "nodes": {"n_a": {"register": {"code": "dry", "severity": "warning"}}},
    }

    result = walk_tree(compiled, _ctx())

    assert result.error == "register node 'n_a' missing 'next' pointer"


def test_the_callers_context_is_not_mutated() -> None:
    compiled = {
        "root": "n_a",
        "nodes": {
            "n_a": {"set": {"x": 1}, "next": "n_b"},
            "n_b": {"register": {"code": "dry", "severity": "info"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }
    ctx = _ctx()

    walk_tree(compiled, ctx)

    assert ctx.vars == {}
    assert ctx.findings == frozenset()


# --- the fold ---------------------------------------------------------------


def test_an_empty_fold_produces_no_card() -> None:
    assert fold([], catalogue=CATALOGUE) is None


def test_one_finding() -> None:
    card = fold([_reg("dry", "warning", "n_dry")], catalogue=CATALOGUE)

    assert card is not None
    assert card.identity == ("dry",)
    assert card.severity == "warning"
    assert card.status == "stressed"
    assert card.action_type == "irrigate"
    assert card.text_en == "Leaf water is low."
    assert card.text_ar == "ماء الورقة منخفض."
    assert card.composed is True
    assert card.rule_code is None


def test_three_findings_with_an_exact_combination_rule() -> None:
    rules = [
        CombinationRule(
            codes=frozenset({"dry", "ndvi_low", "pest_high"}),
            text_en="Water shortage is the cause. Irrigate before treating anything else.",
            text_ar="نقص الري هو السبب. اسقِ قبل أي معالجة أخرى.",
            action_type="irrigate",
            status="stressed",
            code="water_first",
        )
    ]

    card = fold(
        [
            _reg("ndvi_low", "warning", "n1"),
            _reg("dry", "warning", "n2"),
            _reg("pest_high", "critical", "n3"),
        ],
        catalogue=CATALOGUE,
        rules=rules,
    )

    assert card is not None
    assert card.composed is False
    assert card.rule_code == "water_first"
    assert card.text_en.startswith("Water shortage is the cause.")
    assert card.text_ar == "نقص الري هو السبب. اسقِ قبل أي معالجة أخرى."
    assert card.action_type == "irrigate"
    assert card.severity == "critical"
    # The rule replaces the sentence, never the advice under it.
    assert card.actions["immediate"][0]["text_en"] == "Irrigate this block"
    assert card.actions["short_term"][0]["text_en"] == "Plan a protectant spray"


def test_three_findings_with_no_rule_compose_in_both_languages() -> None:
    # A rule that matches two of the three must not fire: matching is exact.
    rules = [
        CombinationRule(
            codes=frozenset({"dry", "ndvi_low"}),
            text_en="Water shortage is the cause.",
            code="pair_only",
        )
    ]

    card = fold(
        [
            _reg("ndvi_low", "warning", "n1"),
            _reg("dry", "warning", "n2"),
            _reg("pest_high", "critical", "n3"),
        ],
        catalogue=CATALOGUE,
        rules=rules,
    )

    assert card is not None
    assert card.composed is True
    assert card.rule_code is None
    assert card.text_en == (
        "Anthracnose pressure is 78 out of 100, leaf water is low, " "and canopy vigour dropped."
    )
    assert card.text_ar == (
        "ضغط الأنثراكنوز 78 من 100، وماء الورقة منخفض، وتراجعت حيوية المجموع الخضري."
    )
    # Worst finding sets both, with no author to say otherwise.
    assert card.severity == "critical"
    assert card.action_type == "spray"
    assert card.status == "stressed"
    assert card.identity == ("dry", "ndvi_low", "pest_high")


def test_two_composed_clauses_use_and_not_a_comma() -> None:
    card = fold(
        [_reg("dry", "warning", "n1"), _reg("ndvi_low", "warning", "n2")],
        catalogue=CATALOGUE,
    )

    assert card is not None
    assert card.text_en == "Leaf water is low and canopy vigour dropped."
    assert card.text_ar == "ماء الورقة منخفض، وتراجعت حيوية المجموع الخضري."


def test_a_repeat_register_folds_as_one_entry_at_its_raised_severity() -> None:
    compiled = {
        "root": "n_a",
        "nodes": {
            "n_a": {"register": {"code": "dry", "severity": "warning"}, "next": "n_b"},
            "n_b": {"register": {"code": "dry", "severity": "critical"}, "next": "n_end"},
            "n_end": {"stop": True},
        },
    }

    result = walk_tree(compiled, _ctx())
    card = fold(result.findings, catalogue=CATALOGUE)

    assert card is not None
    assert card.identity == ("dry",)
    assert card.severity == "critical"
    assert card.findings[0].registered_by == ("n_a", "n_b")


def test_arabic_is_dropped_whole_when_one_clause_has_none() -> None:
    card = fold(
        [_reg("dry", "warning", "n1"), _reg("no_arabic", "warning", "n2")],
        catalogue=CATALOGUE,
    )

    assert card is not None
    assert card.text_en == "Leaf water is low and the trap count rose."
    assert card.text_ar is None


def test_status_is_the_worst_default_status() -> None:
    card = fold([_reg("ndvi_low", "info", "n1")], catalogue=CATALOGUE)
    assert card is not None
    assert card.status == "watch"

    card = fold(
        [_reg("ndvi_low", "info", "n1"), _reg("dry", "info", "n2")],
        catalogue=CATALOGUE,
    )
    assert card is not None
    assert card.status == "stressed"


def test_a_code_the_catalogue_does_not_hold_is_refused() -> None:
    with pytest.raises(UnknownFindingError):
        fold([_reg("ghost", "warning", "n1")], catalogue=CATALOGUE)


def test_parse_combination_rules_drops_what_it_cannot_read() -> None:
    rules = parse_combination_rules(
        [
            {"findings": ["dry", "ndvi_low"], "text_en": "ok", "status": "watch", "code": "r1"},
            {"findings": [], "text_en": "no codes"},
            {"findings": ["dry"], "text_en": ""},
            {"findings": ["dry"], "text_en": "bad status", "status": "on_fire"},
            "not an object",
        ]
    )

    assert len(rules) == 2
    assert rules[0].codes == frozenset({"dry", "ndvi_low"})
    assert rules[0].status == "watch"
    assert rules[1].status is None


# --- the real catalogue row -------------------------------------------------
#
# `Def` above is a stand-in. These two read the class that actually ships, so a
# rename there fails here rather than at whatever later point the two are first
# wired together.

# Every attribute `fold` reads off a catalogue row. Spelled out rather than
# derived from the Protocol, because a Protocol of read-only properties carries
# no class-level annotations to derive them from.
_CONTRACT_FIELDS = (
    "code",
    "clause_en",
    "clause_ar",
    "name_en",
    "name_ar",
    "default_status",
    "source",
)


def test_the_shipped_catalogue_row_carries_every_field_the_fold_reads() -> None:
    import dataclasses

    from app.modules.recommendations.findings import FindingDef as RealFindingDef

    names = {f.name for f in dataclasses.fields(RealFindingDef)}
    missing = sorted(set(_CONTRACT_FIELDS) - names)
    assert not missing, (
        f"findings.FindingDef no longer carries {missing}. The folding engine "
        "declares a local Protocol with these names; rename them in both or in "
        "neither."
    )


def test_a_shipped_catalogue_row_folds_and_shows_the_missing_action_type() -> None:
    """The shipped row has no `action_type` and no `actions`.

    Section 5.4 of the design says the action type with no combination rule is
    the highest severity finding's, and that every finding contributes its own
    horizon items. The catalogue carries neither, so the fold falls back to
    `scout` and the card gets no horizon items at all. This test pins that, so
    the gap is visible in a test name rather than discovered on a real card.
    """
    from app.modules.recommendations.findings import FindingDef as RealFindingDef

    real = {
        "dry": RealFindingDef(
            code="dry",
            clause_en="leaf water is low",
            clause_ar="ماء الورقة منخفض",
            name_en="Water shortage",
            name_ar="نقص الري",
            default_status="stressed",
            source="platform",
        )
    }

    card = fold([_reg("dry", "critical", "n_dry")], catalogue=real)

    assert card is not None
    assert card.text_en == "Leaf water is low."
    assert card.text_ar == "ماء الورقة منخفض."
    assert card.status == "stressed"
    assert card.action_type == "scout"
    assert card.actions == {}
