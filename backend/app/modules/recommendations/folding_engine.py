"""The folding walk and the fold — a second engine beside ``engine.py``.

``engine.py`` walks a compiled tree and returns at the first leaf it reaches.
That walk cannot remember: once two branches converge, it no longer knows which
one it came from, so remembering "vigour was low" while checking water means
repeating the water subtree once per vigour state. A merged diagnosis tree built
that way is 150 to 250 nodes and 72 leaves, and no agronomist can review it.

This module is the other half of the design in
``docs/proposals/unified-decision-tree-engine.md``. Two changes remove the
multiplication:

  * **A scratchpad.** A ``set`` node writes a named value; a ``vars`` source
    reads it back four branches on.
  * **Register and continue.** A ``register`` node records a finding and the
    walk carries on. The tree becomes a sequence of independent checks rather
    than a cascade of combinations. At ``stop`` the findings are folded into
    one card.

Five node kinds, discriminated by which key is present, the way ``engine.py``
does:

  * ``condition`` + ``on_match`` / ``on_miss`` — the existing decision node,
    unchanged, because the merged tree still asks yes/no questions.
  * ``register`` + ``next`` — record a finding, continue.
  * ``set`` + ``next`` — write variables, continue.
  * ``switch`` — ordered cases on one value, first match wins.
  * ``stop`` — end the walk and fold.

An old-style ``outcome`` leaf is rejected here rather than evaluated: a tree
that mixes leaves with findings has two sources of truth for the card, and the
compiler rejects that shape at publish.

Two behaviours for missing data now live in one tree, deliberately:

  * A plain ``condition`` on a missing value is false and takes ``on_miss``,
    matching ``app/shared/conditions/evaluator.py``.
  * A ``switch`` whose subject value is missing matches no case at all — not
    even the default, which is a fallthrough for values it could compare, not
    a catch-all for absent data — and ends the walk with an error naming the
    node.

Cycle detection is a visited-node set, not a step cap. The old engine cut every
walk at 64 steps (``engine.py:67``), which a merged tree of 40 nodes and 15
ordered checks would hit honestly. A 200-step walk over 200 distinct nodes is
normal here and must finish; revisiting one node is the only cycle.

Nothing in this module reads or writes a database.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from app.modules.recommendations.engine import _build_params
from app.shared.conditions import (
    ConditionContext,
    ConditionParseError,
    parse_value_ref,
    resolve_ref,
)
from app.shared.conditions import evaluate as _evaluate_condition_tree

# Same three values and the same order as ``service.py:_SEVERITY_RANK``. A
# register node carries the severity, not the finding catalogue, because the
# same finding is a warning on one route and critical on another.
_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "critical": 2}

# The four platform health classes (``reports/schemas.py``: CropHealthStatus).
# ``unknown`` sits above ``normal`` and below ``watch`` on purpose: "we could
# not read this" is worse than a clean reading and is not a reason to put a
# block on a watch list.
_STATUS_RANK: dict[str, int] = {"normal": 0, "unknown": 1, "watch": 2, "stressed": 3}

# Mirrors ``engine.py:_ACTION_HORIZONS``. Declared rather than imported so the
# folding card's shape is readable here; ``test_folding_engine.py`` asserts the
# two tuples are equal, so they cannot drift apart silently.
_ACTION_HORIZONS: tuple[str, ...] = (
    "immediate",
    "short_term",
    "long_term",
    "monitoring",
)

# What a finding's own advice is typed as when its catalogue entry declares no
# action type. An observation asks the least of the grower and maps to the
# board's ``observation`` activity, so a missing declaration cannot open the
# wrong work order.
_FALLBACK_ACTION_TYPE = "scout"

# Operators a switch case may use. Each maps onto the shared condition
# dialect's comparison node, so a case is compared exactly the way the same
# test inside a ``condition`` node would be — one coercion rule, not two.
_CASE_OPS: tuple[str, ...] = ("lt", "le", "gt", "ge", "eq", "ne", "in", "between")


class FindingDef(Protocol):
    """One row of the finding catalogue, as the fold needs to read it.

    A structural type rather than an import: the catalogue itself
    (``recommendations/findings.py``) lands in a separate change, and this
    module must compile and be testable before it does.

    Two attributes the fold uses are read with ``getattr`` rather than declared
    here, because they are optional on a catalogue row:

      * ``action_type`` — what the finding asks for. Falls back to
        ``scout`` when absent.
      * ``actions`` — ``{horizon: [{text_en, text_ar}]}``, the finding's own
        guidance. Absent means the finding adds no horizon items.

    Declared as read-only properties, not as plain attributes. A plain
    attribute on a Protocol is invariant, so a catalogue row typing
    ``clause_ar`` as ``str`` would not satisfy a Protocol asking for
    ``str | None`` — the real catalogue class does exactly that, and the
    mismatch surfaces only when the two are first wired together. The fold
    never writes to a definition, so read-only is also the honest shape.
    """

    @property
    def code(self) -> str: ...

    @property
    def clause_en(self) -> str: ...

    @property
    def clause_ar(self) -> str | None: ...

    @property
    def name_en(self) -> str: ...

    @property
    def name_ar(self) -> str | None: ...

    @property
    def default_status(self) -> str: ...

    @property
    def source(self) -> str: ...


class UnknownFindingError(LookupError):
    """A walk registered a code the catalogue does not hold.

    The compiler checks every referenced code at publish, so reaching this at
    runtime means the catalogue and the published tree disagree. It is raised
    rather than swallowed because the alternative is a card that prints a raw
    code at a grower, or one that quietly drops a finding the tree asserted.
    """

    def __init__(self, code: str) -> None:
        super().__init__(f"finding code {code!r} is not in the catalogue")
        self.code = code


@dataclass(frozen=True, slots=True)
class RegisteredFinding:
    """One finding as the walk collected it.

    ``severity`` is the highest severity any register node gave this code on
    this walk. ``registered_by`` is every node id that registered it, in walk
    order — a repeat register is one entry, not two, but the trace still shows
    which checks agreed.
    """

    code: str
    severity: str
    registered_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FoldingPathStep:
    """One node visited, for the trace.

    ``kind`` is the node kind. ``matched`` is the branch a condition took, and
    is ``None`` for every other kind — nothing else has a yes/no answer.
    ``detail`` carries what the node did: the finding it registered, the
    variables it wrote, the case a switch chose.
    """

    node_id: str
    kind: str
    matched: bool | None = None
    label_en: str | None = None
    label_ar: str | None = None
    condition_snapshot: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None


@dataclass(slots=True)
class FoldingWalkResult:
    """What one walk produced, before the fold.

    ``error`` is set and ``stopped_at`` is ``None`` when the walk ended badly —
    a cycle, an unknown node id, a switch with no matchable case. The findings
    collected up to that point are still returned, because the trace is more
    useful with them than without, but a caller must not fold a walk that
    errored: the tree never said it was finished.
    """

    findings: list[RegisteredFinding] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    path: list[FoldingPathStep] = field(default_factory=list)
    stopped_at: str | None = None
    error: str | None = None
    evaluation_snapshot: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and self.stopped_at is not None


@dataclass(frozen=True, slots=True)
class CombinationRule:
    """Author-written text for one exact finding set.

    ``codes`` matches only on equality, never on containment (decision 7). That
    is what makes a third finding send the fold to composition, and it is why
    the composed path below is the main path rather than a fallback.
    """

    codes: frozenset[str]
    text_en: str
    text_ar: str | None = None
    action_type: str | None = None
    status: str | None = None
    code: str | None = None


@dataclass(frozen=True, slots=True)
class FoldedCard:
    """One card, from one walk's findings.

    ``identity`` is the sorted finding codes. It is the key for picking a
    combination rule, for deciding whether an open card went stale, and for
    grouping cells in the Action Center — one key, three uses.

    ``composed`` says which text path ran. The dry-run report counts it, since
    the design expects composition to be the common case.
    """

    identity: tuple[str, ...]
    severity: str
    status: str
    action_type: str
    text_en: str
    text_ar: str | None
    findings: tuple[RegisteredFinding, ...]
    actions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    rule_code: str | None = None
    composed: bool = True


# --- the walk ---------------------------------------------------------------


def walk_tree(  # noqa: PLR0911, PLR0912, PLR0915 - one return per way a walk can end
    compiled: Mapping[str, Any],
    ctx: ConditionContext,
    *,
    param_overrides: Mapping[str, Any] | None = None,
) -> FoldingWalkResult:
    """Walk ``compiled`` from its root, collecting findings and variables.

    Pure: the caller's ``ctx`` is never mutated. Each ``set`` and ``register``
    node rebuilds the context with ``dataclasses.replace`` so a later ``vars``
    or ``findings`` condition reads what earlier nodes wrote.
    """
    params_resolved = _build_params(compiled, param_overrides)
    if params_resolved:
        ctx = replace(ctx, params=params_resolved)

    result = FoldingWalkResult()

    nodes_raw = compiled.get("nodes")
    if not isinstance(nodes_raw, dict):
        result.error = "compiled.nodes missing or not a dict"
        return result
    nodes: dict[str, Any] = nodes_raw

    current = compiled.get("root", "root")
    if not isinstance(current, str):
        result.error = "compiled.root missing or not a string"
        return result

    findings: dict[str, RegisteredFinding] = {}
    variables: dict[str, Any] = {}
    visited: set[str] = set()
    came_from: str | None = None

    while True:
        if current in visited:
            result.error = (
                f"cycle: node {came_from!r} leads back to {current!r}, "
                "already visited on this walk"
            )
            return _finish(result, findings, variables)
        visited.add(current)

        node = nodes.get(current)
        if not isinstance(node, dict):
            result.error = f"unknown node id {current!r}"
            return _finish(result, findings, variables)

        if "stop" in node:
            result.path.append(FoldingPathStep(node_id=current, kind="stop", **_labels(node)))
            result.stopped_at = current
            return _finish(result, findings, variables)

        if "outcome" in node:
            result.error = (
                f"node {current!r} is an old-style outcome leaf; the folding "
                "engine ends a walk at a stop node and folds the findings"
            )
            return _finish(result, findings, variables)

        if "register" in node:
            error = _apply_register(current, node, findings, result)
            if error is not None:
                result.error = error
                return _finish(result, findings, variables)
            ctx = replace(ctx, findings=frozenset(findings))
        elif "set" in node:
            error = _apply_set(current, node, variables, ctx, result)
            if error is not None:
                result.error = error
                return _finish(result, findings, variables)
            ctx = replace(ctx, vars=dict(variables))
        elif "switch" in node:
            next_id, error = _eval_switch(current, node, ctx, result)
            if error is not None:
                result.error = error
                return _finish(result, findings, variables)
            came_from, current = current, str(next_id)
            continue
        elif "condition" in node:
            next_id, error = _eval_condition(current, node, ctx, result)
            if error is not None:
                result.error = error
                return _finish(result, findings, variables)
            came_from, current = current, str(next_id)
            continue
        else:
            result.error = f"node {current!r} has no recognised node kind"
            return _finish(result, findings, variables)

        next_id_raw = node.get("next")
        if not isinstance(next_id_raw, str) or not next_id_raw:
            kind = "register" if "register" in node else "set"
            result.error = f"{kind} node {current!r} missing 'next' pointer"
            return _finish(result, findings, variables)
        came_from, current = current, next_id_raw


def _finish(
    result: FoldingWalkResult,
    findings: Mapping[str, RegisteredFinding],
    variables: Mapping[str, Any],
) -> FoldingWalkResult:
    result.findings = list(findings.values())
    result.variables = dict(variables)
    return result


def _labels(node: Mapping[str, Any]) -> dict[str, Any]:
    return {"label_en": node.get("label_en"), "label_ar": node.get("label_ar")}


def _apply_register(
    node_id: str,
    node: Mapping[str, Any],
    findings: dict[str, RegisteredFinding],
    result: FoldingWalkResult,
) -> str | None:
    raw = node.get("register")
    if not isinstance(raw, dict):
        return f"register node {node_id!r} must carry an object"
    code = raw.get("code")
    if not isinstance(code, str) or not code:
        return f"register node {node_id!r} missing 'code'"
    severity = raw.get("severity", "info")
    if severity not in _SEVERITY_RANK:
        return (
            f"register node {node_id!r} severity {severity!r} must be one of "
            f"{tuple(_SEVERITY_RANK)}"
        )

    existing = findings.get(code)
    if existing is None:
        findings[code] = RegisteredFinding(code=code, severity=severity, registered_by=(node_id,))
        raised = False
    else:
        # One code is one entry. A second register keeps the entry and raises
        # its severity only upwards — a later info check must not talk a
        # critical finding down.
        raised = _SEVERITY_RANK[severity] > _SEVERITY_RANK[existing.severity]
        findings[code] = RegisteredFinding(
            code=code,
            severity=severity if raised else existing.severity,
            registered_by=(*existing.registered_by, node_id),
        )

    result.path.append(
        FoldingPathStep(
            node_id=node_id,
            kind="register",
            detail={
                "code": code,
                "severity": findings[code].severity,
                "repeat": existing is not None,
                "raised": raised,
            },
            **_labels(node),
        )
    )
    return None


def _apply_set(
    node_id: str,
    node: Mapping[str, Any],
    variables: dict[str, Any],
    ctx: ConditionContext,
    result: FoldingWalkResult,
) -> str | None:
    raw = node.get("set")
    if not isinstance(raw, dict):
        return f"set node {node_id!r} must carry an object of name: value"
    if not raw:
        return f"set node {node_id!r} writes nothing"

    written: dict[str, Any] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            return f"set node {node_id!r} has a variable name that is not a string"
        if isinstance(value, dict) and "source" in value:
            # A copy of a live reading, resolved the same way a condition
            # resolves it. Taken at the moment this node runs; nothing
            # re-reads it later.
            try:
                ref = parse_value_ref(value)
            except ConditionParseError as exc:
                return f"set node {node_id!r} variable {name!r}: {exc}"
            resolved = resolve_ref(ref, ctx)
            variables[name] = resolved
            written[name] = resolved
        else:
            variables[name] = value
            written[name] = value

    result.path.append(
        FoldingPathStep(node_id=node_id, kind="set", detail={"wrote": written}, **_labels(node))
    )
    return None


def _eval_switch(  # noqa: PLR0911 - one return per malformed part of a switch
    node_id: str,
    node: Mapping[str, Any],
    ctx: ConditionContext,
    result: FoldingWalkResult,
) -> tuple[str | None, str | None]:
    raw = node.get("switch")
    if not isinstance(raw, dict):
        return None, f"switch node {node_id!r} must carry an object"
    subject = raw.get("on")
    if not isinstance(subject, dict):
        return None, f"switch node {node_id!r} missing 'on' value ref"
    cases = raw.get("cases")
    if not isinstance(cases, list):
        return None, f"switch node {node_id!r} missing 'cases' list"
    default = raw.get("default")
    if not isinstance(default, str) or not default:
        return None, f"switch node {node_id!r} missing 'default' pointer"

    try:
        ref = parse_value_ref(subject)
    except ConditionParseError as exc:
        return None, f"switch node {node_id!r} 'on': {exc}"
    value = resolve_ref(ref, ctx)
    if value is None:
        # Stricter than a plain condition, and deliberately so. The default is
        # the branch for a value the cases did not cover, not a hiding place
        # for a value that was never read. See section 10 of the design: with
        # cell scope a missing index errors every cell in the block, and that
        # has to be visible in the dry run rather than silently defaulted.
        return None, (
            f"switch node {node_id!r} matched no case: {_describe_ref(subject)} "
            "resolved to no value"
        )

    snapshot: dict[str, Any] = {}
    for position, case in enumerate(cases):
        if not isinstance(case, dict):
            return None, f"switch node {node_id!r} case {position} must be an object"
        go = case.get("go")
        if not isinstance(go, str) or not go:
            return None, f"switch node {node_id!r} case {position} missing 'go' pointer"
        comparison = _case_comparison(subject, case)
        if comparison is None:
            return None, (f"switch node {node_id!r} case {position} needs one of {_CASE_OPS}")
        matched, case_snapshot = _evaluate_condition_tree(comparison, ctx)
        snapshot.update(case_snapshot.get("values") or {})
        if matched:
            result.path.append(
                FoldingPathStep(
                    node_id=node_id,
                    kind="switch",
                    condition_snapshot=snapshot,
                    detail={"case": position, "went_to": go},
                    **_labels(node),
                )
            )
            _merge_snapshot(result, snapshot)
            return go, None

    result.path.append(
        FoldingPathStep(
            node_id=node_id,
            kind="switch",
            condition_snapshot=snapshot,
            detail={"case": None, "went_to": default},
            **_labels(node),
        )
    )
    _merge_snapshot(result, snapshot)
    return default, None


def _case_comparison(subject: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any] | None:
    """Turn one switch case into a comparison node of the shared dialect."""
    for op in _CASE_OPS:
        if op not in case:
            continue
        operand = case[op]
        if op == "between":
            if not isinstance(operand, list) or len(operand) != 2:
                return None
            return {"op": "between", "left": dict(subject), "low": operand[0], "high": operand[1]}
        if op == "in":
            if not isinstance(operand, list):
                return None
            return {"op": "in", "left": dict(subject), "values": operand}
        return {"op": op, "left": dict(subject), "right": operand}
    return None


def _eval_condition(
    node_id: str,
    node: Mapping[str, Any],
    ctx: ConditionContext,
    result: FoldingWalkResult,
) -> tuple[str | None, str | None]:
    condition = node.get("condition")
    if not isinstance(condition, dict):
        return None, f"node {node_id!r} condition must be an object"
    tree = condition.get("tree")
    if not isinstance(tree, dict):
        return None, f"node {node_id!r} condition.tree must be an object"

    matched, sub_snapshot = _evaluate_condition_tree(tree, ctx)
    values = dict(sub_snapshot.get("values") or {})
    _merge_snapshot(result, values)
    result.path.append(
        FoldingPathStep(
            node_id=node_id,
            kind="condition",
            matched=matched,
            condition_snapshot=values,
            **_labels(node),
        )
    )

    branch = "on_match" if matched else "on_miss"
    next_id = node.get(branch)
    if not isinstance(next_id, str) or not next_id:
        return None, f"node {node_id!r} missing {branch} pointer"
    return next_id, None


def _merge_snapshot(result: FoldingWalkResult, values: Mapping[str, Any]) -> None:
    for key, value in values.items():
        result.evaluation_snapshot[key] = value


def _describe_ref(raw: Mapping[str, Any]) -> str:
    source = raw.get("source")
    tail = raw.get("index_code") or raw.get("risk_code") or raw.get("code") or raw.get("name")
    field_ = raw.get("field") or raw.get("key")
    return ".".join(str(part) for part in (source, tail, field_) if part)


# --- the fold ---------------------------------------------------------------


def parse_combination_rules(raw: Any) -> list[CombinationRule]:
    """Read a compiled tree's ``combinations:`` block.

    Malformed entries are dropped rather than raised on: the compiler is what
    rejects a bad rule at publish, and a rule that cannot be read here means
    the fold composes instead — the worse text, never the wrong text.
    """
    if not isinstance(raw, list):
        return []
    rules: list[CombinationRule] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        codes = entry.get("findings") or entry.get("codes")
        if not isinstance(codes, list) or not codes:
            continue
        if not all(isinstance(c, str) and c for c in codes):
            continue
        text_en = entry.get("text_en")
        if not isinstance(text_en, str) or not text_en:
            continue
        text_ar = entry.get("text_ar")
        action_type = entry.get("action_type")
        status = entry.get("status")
        rules.append(
            CombinationRule(
                codes=frozenset(codes),
                text_en=text_en,
                text_ar=text_ar if isinstance(text_ar, str) and text_ar else None,
                action_type=action_type if isinstance(action_type, str) and action_type else None,
                status=status if status in _STATUS_RANK else None,
                code=entry.get("code") if isinstance(entry.get("code"), str) else None,
            )
        )
    return rules


def fold(
    findings: Sequence[RegisteredFinding],
    *,
    catalogue: Mapping[str, FindingDef],
    rules: Sequence[CombinationRule] = (),
) -> FoldedCard | None:
    """Fold the findings one walk collected into one card.

    Returns ``None`` for an empty set: the tree ran, found nothing, and the
    cell is healthy. That is the answer, not a missing one.

    Raises ``UnknownFindingError`` when a registered code is not in
    ``catalogue``.
    """
    if not findings:
        return None

    ordered = _order_by_severity(findings)
    for entry in ordered:
        if entry.code not in catalogue:
            raise UnknownFindingError(entry.code)

    identity = tuple(sorted(entry.code for entry in ordered))
    rule = _matching_rule(identity, rules)

    severity = ordered[0].severity
    status = rule.status if rule is not None and rule.status else _worst_status(ordered, catalogue)
    action_type = (
        rule.action_type
        if rule is not None and rule.action_type
        else _action_type_for(ordered, catalogue)
    )

    if rule is not None:
        text_en, text_ar = rule.text_en, rule.text_ar
    else:
        text_en, text_ar = _compose_text(ordered, catalogue)

    return FoldedCard(
        identity=identity,
        severity=severity,
        status=status,
        action_type=action_type,
        text_en=text_en,
        text_ar=text_ar,
        findings=tuple(ordered),
        actions=_merge_actions(ordered, catalogue),
        rule_code=rule.code if rule is not None else None,
        composed=rule is None,
    )


def _order_by_severity(findings: Iterable[RegisteredFinding]) -> list[RegisteredFinding]:
    """Worst first, then by code.

    The code tiebreak is not cosmetic: two walks that reach the same finding
    set by different routes have to produce the same sentence, or the card
    text changes with no change in what was found.
    """
    return sorted(findings, key=lambda f: (-_SEVERITY_RANK.get(f.severity, 0), f.code))


def _matching_rule(
    identity: tuple[str, ...], rules: Sequence[CombinationRule]
) -> CombinationRule | None:
    wanted = frozenset(identity)
    for rule in rules:
        if rule.codes == wanted:
            return rule
    return None


def _worst_status(ordered: Sequence[RegisteredFinding], catalogue: Mapping[str, FindingDef]) -> str:
    worst = "normal"
    for entry in ordered:
        candidate = catalogue[entry.code].default_status
        if _STATUS_RANK.get(candidate, 0) > _STATUS_RANK.get(worst, 0):
            worst = candidate
    return worst


def _action_type_for(
    ordered: Sequence[RegisteredFinding], catalogue: Mapping[str, FindingDef]
) -> str:
    """The worst finding's action type, or the worst one that declares any.

    With no combination rule nobody wrote down the order of operations, so the
    most severe finding is the closest thing to an author's intent.
    """
    for entry in ordered:
        declared = getattr(catalogue[entry.code], "action_type", None)
        if isinstance(declared, str) and declared:
            return declared
    return _FALLBACK_ACTION_TYPE


def _merge_actions(
    ordered: Sequence[RegisteredFinding], catalogue: Mapping[str, FindingDef]
) -> dict[str, list[dict[str, Any]]]:
    """Every finding contributes its horizon items, rule or no rule.

    A combination rule replaces the sentence at the top of the card, never the
    advice underneath it. Items identical in English are kept once — two
    findings that both say "check the emitters" should say it once.
    """
    merged: dict[str, list[dict[str, Any]]] = {}
    for horizon in _ACTION_HORIZONS:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in ordered:
            declared = getattr(catalogue[entry.code], "actions", None)
            if not isinstance(declared, Mapping):
                continue
            for item in declared.get(horizon) or []:
                if not isinstance(item, Mapping):
                    continue
                text_en = item.get("text_en")
                if not isinstance(text_en, str) or not text_en or text_en in seen:
                    continue
                seen.add(text_en)
                text_ar = item.get("text_ar")
                items.append(
                    {
                        "text_en": text_en,
                        "text_ar": text_ar if isinstance(text_ar, str) else None,
                        "finding_code": entry.code,
                    }
                )
        if items:
            merged[horizon] = items
    return merged


# --- composed text ----------------------------------------------------------


def _compose_text(
    ordered: Sequence[RegisteredFinding], catalogue: Mapping[str, FindingDef]
) -> tuple[str, str | None]:
    """Join each finding's clause into one sentence, worst clause first.

    This is the main path, not a fallback. A combination rule fires only on an
    exact finding set, and a third finding is common, so most real cells read a
    composed sentence.

    Arabic is not the English join with Arabic words in it. Clauses are
    separated by the Arabic comma and the last one is introduced by ``و``
    written onto the front of its first word, with no space — "أ، وب، وج". A
    space after the ``و``, or an English comma, reads as a typo to an Arabic
    reader. The Arabic sentence is returned only when every finding carries an
    Arabic clause: half a sentence in each language is worse than one.
    """
    clauses_en = [catalogue[entry.code].clause_en for entry in ordered]
    text_en = _as_sentence_en(_join_en(clauses_en))

    clauses_ar_raw = [catalogue[entry.code].clause_ar for entry in ordered]
    if any(not clause for clause in clauses_ar_raw):
        return text_en, None
    clauses_ar = [str(clause) for clause in clauses_ar_raw]
    return text_en, _as_sentence_ar(_join_ar(clauses_ar))


def _join_en(clauses: Sequence[str]) -> str:
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _join_ar(clauses: Sequence[str]) -> str:
    if len(clauses) == 1:
        return clauses[0]
    # Every clause after the first takes the waw, not only the last one:
    # Arabic has no "A, B and C" shape. And the waw is written onto the front
    # of the word that follows it, with no space after it.
    return clauses[0] + "، و" + "، و".join(clauses[1:])


def _as_sentence_en(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _as_sentence_ar(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    # No capitalisation in Arabic; the full stop is the Latin one, which is
    # what every Arabic string already shipped in this repository uses.
    if text[-1] not in ".!؟":
        text += "."
    return text
