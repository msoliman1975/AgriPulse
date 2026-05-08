"""Pure-function rule evaluation for the alerts engine.

The Beat task and the on-demand `evaluate_block` service path both feed
their loaded rules + signal snapshots through these helpers; the DB
layer never sees the merged-rule structure.

Three concerns:

  1. **Merging.** The platform `default_rules` rows are immutable from
     the tenant side. Tenants customise via `rule_overrides`. The
     engine merges them into an *effective* rule per evaluation by
     picking the override field if non-null, else the default field.
  2. **Predicate dispatch.** Conditions JSONB carries a ``type``
     discriminator. The engine has a small dispatch table mapping each
     supported type to a pure evaluator. New predicate kinds arrive
     by adding an entry; older alert rows keep working because the
     `signal_snapshot` JSONB stored at fire-time captures the
     interpretation that was current then.
  3. **Crop-category filter.** A rule's
     ``applies_to_crop_categories`` empty list means "any crop";
     non-empty filters by the block's current crop category.

Predicate types currently supported:

  * ``baseline_deviation_below`` — ``signals.baseline_deviation < threshold``
  * ``baseline_deviation_between`` — ``low <= signals.baseline_deviation <= high``
  * ``condition_tree`` — arbitrary tree from ``app.shared.conditions``;
    delegates to its evaluator, which reads from a ``ConditionContext``
    derived from the same ``BlockSignals`` snapshot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.shared.conditions import ConditionContext, SignalEntry, WeatherSnapshot
from app.shared.conditions import evaluate as _evaluate_tree


@dataclass(frozen=True, slots=True)
class Rule:
    """Effective rule after merge — what the engine actually evaluates."""

    code: str
    severity: str
    conditions: dict[str, Any]
    actions: dict[str, Any]
    applies_to_crop_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlockSignals:
    """Signals available for evaluating one block.

    Loaded once per block per evaluation pass; rules read whichever
    fields they need. Adding a new field doesn't break existing rules.
    """

    block_id: str
    crop_category: str | None
    latest_index_aggregates: dict[str, dict[str, Any]]
    """``{index_code: {"mean": Decimal, "baseline_deviation": Decimal | None,
    "time": datetime}, ...}``"""
    weather: WeatherSnapshot | None = None
    """Pre-loaded weather snapshot for the block's farm. ``None`` when
    the alerts service skips the weather load (e.g. tests, on-demand
    eval that doesn't care about weather rules) — predicates that
    reference weather refs branch to ``on_miss``."""
    signals: dict[str, SignalEntry] | None = None
    """Latest observation per applicable signal_code. ``None`` is
    treated as "loader skipped" — same permissive semantics as weather."""


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    """Result of a successful rule evaluation, ready to insert."""

    rule_code: str
    severity: str
    diagnosis_en: str | None
    diagnosis_ar: str | None
    prescription_en: str | None
    prescription_ar: str | None
    signal_snapshot: dict[str, Any]


# ---- Merging --------------------------------------------------------------


def merge_rule(
    *,
    default: dict[str, Any],
    override: dict[str, Any] | None,
) -> Rule | None:
    """Apply a tenant override on top of a platform default.

    Returns ``None`` when the override's ``is_disabled`` flag is set —
    the engine treats a disabled rule as absent. Both inputs are dict
    rows from their respective tables; this function is shape-agnostic
    so the repository can pass mappings directly.
    """
    if override is not None and override.get("is_disabled"):
        return None

    severity = default["severity"]
    conditions = default["conditions"]
    actions = default["actions"]
    if override is not None:
        if override.get("modified_severity"):
            severity = override["modified_severity"]
        if override.get("modified_conditions"):
            conditions = override["modified_conditions"]
        if override.get("modified_actions"):
            actions = override["modified_actions"]

    return Rule(
        code=default["code"],
        severity=severity,
        conditions=conditions,
        actions=actions,
        applies_to_crop_categories=tuple(default.get("applies_to_crop_categories") or ()),
    )


# ---- Predicate dispatch ---------------------------------------------------


def _signal_for_index(signals: BlockSignals, index_code: str, key: str) -> Decimal | None:
    """Pull a per-index value out of the signal snapshot.

    Returns None when the index hasn't been observed for this block,
    or the requested key is missing — both are ``rule does not apply``
    rather than "rule fires".
    """
    row = signals.latest_index_aggregates.get(index_code)
    if row is None:
        return None
    val = row.get(key)
    if val is None:
        return None
    return val if isinstance(val, Decimal) else Decimal(str(val))


def _predicate_baseline_deviation_below(
    conditions: dict[str, Any], signals: BlockSignals
) -> tuple[bool, dict[str, Any]]:
    index_code = str(conditions.get("index_code", "ndvi"))
    threshold = Decimal(str(conditions["threshold"]))
    deviation = _signal_for_index(signals, index_code, "baseline_deviation")
    if deviation is None:
        return False, {}
    fired = deviation < threshold
    snapshot: dict[str, Any] = {
        "index_code": index_code,
        "baseline_deviation": str(deviation),
        "threshold": str(threshold),
    }
    return fired, snapshot


def _predicate_baseline_deviation_between(
    conditions: dict[str, Any], signals: BlockSignals
) -> tuple[bool, dict[str, Any]]:
    index_code = str(conditions.get("index_code", "ndvi"))
    low = Decimal(str(conditions["low"]))
    high = Decimal(str(conditions["high"]))
    deviation = _signal_for_index(signals, index_code, "baseline_deviation")
    if deviation is None:
        return False, {}
    fired = low <= deviation <= high
    snapshot: dict[str, Any] = {
        "index_code": index_code,
        "baseline_deviation": str(deviation),
        "range": [str(low), str(high)],
    }
    return fired, snapshot


def _predicate_condition_tree(
    conditions: dict[str, Any], signals: BlockSignals
) -> tuple[bool, dict[str, Any]]:
    """Delegate to the shared condition-tree evaluator.

    Rule body shape: ``{"type": "condition_tree", "tree": {...}}``. The
    evaluator is permissive on malformed trees — returns ``(False, {})``
    rather than raising — so a typo'd rule doesn't break a sweep.
    """
    tree = conditions.get("tree")
    if not isinstance(tree, dict):
        return False, {}
    ctx = ConditionContext.from_block_signals(
        block_id=signals.block_id,
        crop_category=signals.crop_category,
        latest_index_aggregates=signals.latest_index_aggregates,
        weather=signals.weather,
        signals=signals.signals,
    )
    return _evaluate_tree(tree, ctx)


_PREDICATE_DISPATCH: dict[
    str, Callable[[dict[str, Any], BlockSignals], tuple[bool, dict[str, Any]]]
] = {
    "baseline_deviation_below": _predicate_baseline_deviation_below,
    "baseline_deviation_between": _predicate_baseline_deviation_between,
    "condition_tree": _predicate_condition_tree,
}


def evaluate_predicate(
    conditions: dict[str, Any], signals: BlockSignals
) -> tuple[bool, dict[str, Any]]:
    """Dispatch on ``conditions['type']`` to the matching evaluator.

    Unknown types log via the caller (the service) and skip the rule.
    Returning ``(False, {})`` here keeps the engine permissive: a
    typo'd rule body won't crash a tenant's nightly sweep.
    """
    pred_type = conditions.get("type")
    if not isinstance(pred_type, str):
        return False, {}
    handler = _PREDICATE_DISPATCH.get(pred_type)
    if handler is None:
        return False, {}
    return handler(conditions, signals)


# ---- Whole-rule evaluation -----------------------------------------------


def evaluate_rule(rule: Rule, signals: BlockSignals) -> AlertCandidate | None:
    """Run a merged rule against block signals.

    Order of checks:
      1. Crop-category filter (empty list = any crop).
      2. Predicate evaluation. ``False`` → no alert.
      3. Build an ``AlertCandidate`` with the signals snapshot embedded
         so downstream readers can audit what triggered the alert
         even if the rule body has since changed.
    """
    if (
        rule.applies_to_crop_categories
        and signals.crop_category not in rule.applies_to_crop_categories
    ):
        return None

    fired, snapshot = evaluate_predicate(rule.conditions, signals)
    if not fired:
        return None

    actions = rule.actions
    return AlertCandidate(
        rule_code=rule.code,
        severity=rule.severity,
        diagnosis_en=actions.get("diagnosis_en"),
        diagnosis_ar=actions.get("diagnosis_ar"),
        prescription_en=actions.get("prescription_en"),
        prescription_ar=actions.get("prescription_ar"),
        signal_snapshot=snapshot,
    )
