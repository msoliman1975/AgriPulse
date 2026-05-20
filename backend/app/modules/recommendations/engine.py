"""Pure-function decision-tree evaluation.

A compiled tree is a dict produced by ``loader.compile_tree`` from the
authored YAML. Two node kinds:

  * **Decision node** — has a ``condition`` (a tree dialect from
    ``app.shared.conditions``) plus ``on_match`` / ``on_miss`` pointers
    to the next node id.
  * **Leaf node** — has an ``outcome`` dict with the action_type,
    parameters, severity, confidence, text_en/text_ar.

Compiled tree shape::

    {
        "code": "scout_for_stress_v1",
        "name_en": "...", "name_ar": "...",
        "description_en": "...", "description_ar": "...",
        "crop_code": null,
        "applicable_regions": [],
        "root": "root",
        "nodes": {
            "<node_id>": {
                "condition": {"tree": {...}},      # decision node
                "on_match": "<node_id>",
                "on_miss":  "<node_id>",
                "label_en": "...", "label_ar": "..."  # optional
            },
            "<leaf_id>": {
                "outcome": {
                    "action_type": "scout",
                    "severity": "warning",
                    "confidence": 0.65,
                    "parameters": {...},
                    "text_en": "...", "text_ar": "...",
                    "valid_for_hours": 72  # optional
                },
                "label_en": "...", "label_ar": "..."
            }
        }
    }

Evaluation walks the tree from ``root``; at each decision node the
condition is evaluated against a pre-loaded ``ConditionContext`` and the
appropriate branch is followed. The path of node ids visited (and the
labels for explainability) is captured in ``EvaluationResult.path``.

Cycles in a malformed tree are bounded by ``_MAX_STEPS`` so a typo'd
``on_match`` pointing back to itself can't hang a sweep — the evaluator
returns ``None`` instead.

Permissive on missing data: a condition that resolves to None branches
to ``on_miss`` (mirrors the shared evaluator's "missing data → False"
semantics). Unknown node ids surface as ``EvaluationResult(outcome=None,
error=...)`` for the caller to log.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from app.shared.conditions import ConditionContext
from app.shared.conditions import evaluate as _evaluate_condition_tree

_MAX_STEPS = 64


def _build_params(
    compiled: Mapping[str, Any],
    overrides: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve parameter values for one tree evaluation (PR-B).

    Starts with the defaults declared in ``compiled.parameters``, then
    layers any ``overrides`` on top. PR-C plumbs tenant-level overrides
    into this slot; for now most callers pass ``None`` and only
    defaults apply. Overrides for parameters not declared in the tree
    are silently dropped — they'd indicate either a stale override or
    a typo, and we'd rather fail closed than apply a phantom value.
    """
    decl = compiled.get("parameters") or {}
    resolved: dict[str, Any] = {}
    if isinstance(decl, dict):
        for name, decl_entry in decl.items():
            if isinstance(decl_entry, dict) and "default" in decl_entry:
                resolved[name] = decl_entry["default"]
    if overrides:
        for k, v in overrides.items():
            if k in resolved:
                resolved[k] = v
    return resolved


def _substitute_params_in_outcome_params(
    raw: Any, params: Mapping[str, Any]
) -> Any:
    """Replace any ``{source: params, name: x}`` ref dict found inside
    an outcome.parameters value with the resolved literal.

    Recursive: handles nested dicts and lists so a parameter can be a
    structured value containing nested refs. Refs to undeclared names
    resolve to ``None`` — the engine writes that into the persisted
    ``recommendations.parameters`` JSONB, which is the same shape
    consumers already handle for missing optional fields.
    """
    if isinstance(raw, dict):
        if raw.get("source") == "params":
            name = raw.get("name")
            return params.get(name) if isinstance(name, str) else None
        return {k: _substitute_params_in_outcome_params(v, params) for k, v in raw.items()}
    if isinstance(raw, list):
        return [_substitute_params_in_outcome_params(v, params) for v in raw]
    return raw


@dataclass(frozen=True, slots=True)
class TreeOutcome:
    """Resolved leaf outcome — what the service writes into recommendations."""

    action_type: str
    severity: str
    confidence: Decimal
    parameters: dict[str, Any]
    text_en: str
    text_ar: str | None
    valid_for_hours: int | None


@dataclass(frozen=True, slots=True)
class TreePathStep:
    """One node visited during evaluation. Stored in ``recommendations.tree_path``
    for explainability — the recommendations detail UI renders the chain.
    """

    node_id: str
    matched: bool | None  # None for leaf nodes
    label_en: str | None
    label_ar: str | None
    condition_snapshot: dict[str, Any] | None


@dataclass(slots=True)
class EvaluationResult:
    outcome: TreeOutcome | None
    path: list[TreePathStep] = field(default_factory=list)
    error: str | None = None
    evaluation_snapshot: dict[str, Any] = field(default_factory=dict)


def evaluate_tree(  # noqa: PLR0911 - tree-walk returns at each leaf/cut
    compiled: Mapping[str, Any],
    ctx: ConditionContext,
    *,
    param_overrides: Mapping[str, Any] | None = None,
) -> EvaluationResult:
    """Walk ``compiled`` from its root with ``ctx`` and return the result.

    Returns ``EvaluationResult.outcome = None`` when the tree leaves on
    a leaf with ``action_type == 'no_action'`` (the engine still records
    the path so debug callers can see which branch the block hit). The
    service treats outcome=None as "do not write a recommendation".

    ``param_overrides`` (PR-B): values that override the tree's
    declared parameter defaults. Resolved params land on ``ctx.params``
    for the duration of this evaluation so any ``$params.x`` refs
    inside conditions resolve to either the override or the default.
    PR-C will populate this from ``tenant.tree_parameter_overrides``.
    """
    params_resolved = _build_params(compiled, param_overrides)
    # Don't mutate the caller's ctx — every block in a sweep shares the
    # same data ctx but each tree builds its own params dict.
    ctx = replace(ctx, params=params_resolved) if params_resolved else ctx

    nodes_raw = compiled.get("nodes")
    if not isinstance(nodes_raw, dict):
        return EvaluationResult(outcome=None, error="compiled.nodes missing or not a dict")
    nodes: dict[str, Any] = nodes_raw

    current = compiled.get("root", "root")
    if not isinstance(current, str):
        return EvaluationResult(outcome=None, error="compiled.root missing or not a string")

    path: list[TreePathStep] = []
    snapshot_acc: dict[str, Any] = {}

    for _ in range(_MAX_STEPS):
        node = nodes.get(current)
        if not isinstance(node, dict):
            return EvaluationResult(
                outcome=None,
                path=path,
                error=f"unknown node id {current!r}",
                evaluation_snapshot=snapshot_acc,
            )

        if "outcome" in node:
            path.append(_step_for_leaf(current, node))
            outcome = _parse_outcome(node["outcome"], params=params_resolved)
            return EvaluationResult(
                outcome=outcome,
                path=path,
                evaluation_snapshot=snapshot_acc,
            )

        condition = node.get("condition")
        if not isinstance(condition, dict):
            return EvaluationResult(
                outcome=None,
                path=path,
                error=f"node {current!r} has no condition or outcome",
                evaluation_snapshot=snapshot_acc,
            )
        tree = condition.get("tree")
        if not isinstance(tree, dict):
            return EvaluationResult(
                outcome=None,
                path=path,
                error=f"node {current!r} condition.tree must be an object",
                evaluation_snapshot=snapshot_acc,
            )

        matched, sub_snapshot = _evaluate_condition_tree(tree, ctx)
        # Merge resolved values across nodes; later nodes overwrite the
        # same ref with the same resolution (deterministic).
        for key, value in (sub_snapshot.get("values") or {}).items():
            snapshot_acc[key] = value

        path.append(
            TreePathStep(
                node_id=current,
                matched=matched,
                label_en=node.get("label_en"),
                label_ar=node.get("label_ar"),
                condition_snapshot=dict(sub_snapshot.get("values") or {}),
            )
        )

        next_id = node.get("on_match" if matched else "on_miss")
        if not isinstance(next_id, str):
            return EvaluationResult(
                outcome=None,
                path=path,
                error=f"node {current!r} missing {'on_match' if matched else 'on_miss'} pointer",
                evaluation_snapshot=snapshot_acc,
            )
        current = next_id

    return EvaluationResult(
        outcome=None,
        path=path,
        error=f"tree exceeded {_MAX_STEPS} steps — likely a cycle",
        evaluation_snapshot=snapshot_acc,
    )


def _step_for_leaf(node_id: str, node: Mapping[str, Any]) -> TreePathStep:
    return TreePathStep(
        node_id=node_id,
        matched=None,
        label_en=node.get("label_en"),
        label_ar=node.get("label_ar"),
        condition_snapshot=None,
    )


def _parse_outcome(raw: Any, *, params: Mapping[str, Any]) -> TreeOutcome | None:
    if not isinstance(raw, dict):
        return None
    action_type = raw.get("action_type")
    text_en = raw.get("text_en")
    if not isinstance(action_type, str) or not isinstance(text_en, str):
        return None

    confidence_raw = raw.get("confidence", 0.5)
    try:
        confidence = Decimal(str(confidence_raw))
    except (ArithmeticError, ValueError):
        confidence = Decimal("0.5")
    if confidence < 0 or confidence > 1:
        confidence = max(Decimal("0"), min(Decimal("1"), confidence))

    valid_for_hours_raw = raw.get("valid_for_hours")
    valid_for_hours: int | None = None
    if isinstance(valid_for_hours_raw, int) and valid_for_hours_raw > 0:
        valid_for_hours = valid_for_hours_raw

    # Outcome.parameters may contain `{source: params, name: x}` refs;
    # substitute them to literals here so the persisted row in
    # `recommendations.parameters` is a plain JSONB object the rest
    # of the system can consume without knowing about refs (PR-B).
    raw_parameters = dict(raw.get("parameters") or {})
    parameters = _substitute_params_in_outcome_params(raw_parameters, params)

    return TreeOutcome(
        action_type=action_type,
        severity=str(raw.get("severity", "info")),
        confidence=confidence,
        parameters=parameters if isinstance(parameters, dict) else {},
        text_en=text_en,
        text_ar=raw.get("text_ar"),
        valid_for_hours=valid_for_hours,
    )
