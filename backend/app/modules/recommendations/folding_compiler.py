"""Compile and check a folding decision tree.

A folding tree is the new shape described in
``docs/proposals/unified-decision-tree-engine.md`` section 6.5. Instead of
ending at one ``outcome`` leaf that says everything, the walk passes through
``register`` nodes that each record one finding, and ends at a single ``stop``
node where the engine folds the findings into one card.

Four node kinds carry the new shape:

  * ``register`` — records a finding code with a severity, then ``next``.
  * ``set``      — writes one or more variables, then ``next``.
  * ``switch``   — ordered cases, first match wins, ``default`` required.
  * ``stop``     — ends the walk and triggers the fold.

The old ``condition`` / ``on_match`` / ``on_miss`` decision node is kept
unchanged. The old ``outcome`` leaf is not: a tree that mixes an outcome leaf
with a register or stop node is rejected, which is what lets the sweep pick
the right engine from the tree's shape alone.

This module never evaluates a tree. It validates a definition and returns the
compiled body. It is a second, stricter check beside
``loader._validate_reachability``: that one asks whether a node can be
reached, this one asks whether every path through the tree ends at ``stop``.

Errors are returned as structured objects, not formatted strings, because the
beta designer renders them beside the node they name and has to render them in
Arabic as well.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Container, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.modules.recommendations.errors import DecisionTreeParseError
from app.modules.recommendations.loader import (
    _validate_condition_ops,
    _validate_parameters_block,
    _validate_params_refs,
    _validate_targeting,
)

# The severity a register node may name. Severity lives on the node, not on
# the finding catalogue, so one finding can be a warning on one route and
# critical on another (section 4.1).
SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")

# The health class a combination rule may force. This is the folding engine's
# own vocabulary and is deliberately not ``status_codes.STATUS_CODES``, which
# is the leaf verdict list the old shape uses.
FOLDING_STATUSES: tuple[str, ...] = ("normal", "watch", "stressed", "unknown")

# Every comparison operator a switch case may use. The same list the shared
# evaluator implements, so a case cannot ask a question the engine has no
# answer for.
SWITCH_CASE_OPS: frozenset[str] = frozenset({"lt", "le", "gt", "ge", "eq", "ne", "between", "in"})

# Hard cap on every graph pass here, mirroring the 1024-step cap the current
# reachability check uses (``loader.py:537-549``). The walks below all settle
# by fixpoint, so a cycle cannot spin for ever, but the cap means a malformed
# tree fails fast instead of eating a publish request.
MAX_STEPS: int = 1024


# ---------------------------------------------------------------------
# Structured errors
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompileError:
    """One reason a tree cannot be published.

    ``node_ids`` holds every node the rule complains about, so the "a path
    ends without stop" rule can name all of them rather than the first one it
    happened to find. ``rule`` is a stable machine key the designer can branch
    on; the two message fields are what a person reads.
    """

    rule: str
    message_en: str
    message_ar: str
    node_ids: tuple[str, ...] = ()

    @property
    def node_id(self) -> str | None:
        """The first node named, or ``None`` for a whole-tree problem."""
        return self.node_ids[0] if self.node_ids else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "message_en": self.message_en,
            "message_ar": self.message_ar,
            "node_ids": list(self.node_ids),
        }


class FoldingCompileError(Exception):
    """Raised by :func:`compile_folding_tree` with every error found.

    The compiler collects rather than stopping at the first problem. An
    author fixing one message at a time through a publish round trip is the
    slow path the designer is meant to remove.
    """

    def __init__(self, errors: Iterable[CompileError]) -> None:
        self.errors: tuple[CompileError, ...] = tuple(errors)
        super().__init__("; ".join(e.message_en for e in self.errors))

    def as_dict(self) -> dict[str, Any]:
        return {"errors": [e.as_dict() for e in self.errors]}


@dataclass
class _Collector:
    errors: list[CompileError] = field(default_factory=list)

    def add(self, rule: str, message_en: str, message_ar: str, *nodes: str) -> None:
        self.errors.append(
            CompileError(
                rule=rule,
                message_en=message_en,
                message_ar=message_ar,
                node_ids=tuple(nodes),
            )
        )


# ---------------------------------------------------------------------
# Node kinds
# ---------------------------------------------------------------------


def kind_of_node(node: Any) -> str:
    """Which kind a node body is, by the key it carries.

    Returns one of ``register``, ``set``, ``switch``, ``stop``, ``outcome``,
    ``condition``, or ``unknown``. The discriminator is the present key, as
    the engine already does it (``engine.py:5-11``).
    """
    if not isinstance(node, dict):
        return "unknown"
    for key in ("register", "set", "switch", "stop", "outcome"):
        if key in node:
            return key
    if "condition" in node:
        return "condition"
    return "unknown"


def is_folding_shape(spec: Any) -> bool:
    """True when the definition uses the new shape.

    The sweep dispatches on this, so it reads the shape and nothing else: one
    ``register`` or ``stop`` node anywhere means folding.
    """
    nodes = spec.get("nodes") if isinstance(spec, dict) else None
    if not isinstance(nodes, dict):
        return False
    return any(kind_of_node(n) in ("register", "stop") for n in nodes.values())


def _successors(node: Any) -> list[str]:
    """The node ids this node can hand the walk to.

    Only well-formed pointers are returned. A broken pointer already has its
    own error from :func:`_check_targets`, and leaving it out of the graph is
    what makes the branch read as a dead end in the path walk.
    """
    kind = kind_of_node(node)
    if kind in ("stop", "outcome", "unknown"):
        return []
    if kind in ("register", "set"):
        nxt = node.get("next")
        return [nxt] if isinstance(nxt, str) else []
    if kind == "switch":
        switch = node.get("switch")
        if not isinstance(switch, dict):
            return []
        out: list[str] = []
        cases = switch.get("cases")
        if isinstance(cases, list):
            for case in cases:
                if isinstance(case, dict) and isinstance(case.get("go"), str):
                    out.append(case["go"])
        default = switch.get("default")
        if isinstance(default, str):
            out.append(default)
        return out
    # condition
    out = []
    for branch in ("on_match", "on_miss"):
        target = node.get(branch)
        if isinstance(target, str):
            out.append(target)
    return out


# ---------------------------------------------------------------------
# Value references
# ---------------------------------------------------------------------


def _vars_reads(value: Any) -> list[str]:
    """Every ``{source: vars, name: x}`` name inside one value."""
    found: list[str] = []

    def _walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("source") == "vars":
                name = item.get("name")
                if isinstance(name, str) and name:
                    found.append(name)
                return
            for child in item.values():
                _walk(child)
        elif isinstance(item, list):
            for child in item:
                _walk(child)

    _walk(value)
    return found


def _node_vars_reads(node: Any) -> list[str]:
    """Every variable one node reads, before its own writes land."""
    if not isinstance(node, dict):
        return []
    reads: list[str] = []
    condition = node.get("condition")
    if isinstance(condition, dict):
        reads.extend(_vars_reads(condition.get("tree")))
    switch = node.get("switch")
    if isinstance(switch, dict):
        reads.extend(_vars_reads(switch.get("on")))
        reads.extend(_vars_reads(switch.get("cases")))
    setter = node.get("set")
    if isinstance(setter, dict):
        for item in setter.values():
            reads.extend(_vars_reads(item))
    outcome = node.get("outcome")
    if isinstance(outcome, dict):
        reads.extend(_vars_reads(outcome.get("parameters")))
    return reads


def _node_vars_writes(node: Any) -> set[str]:
    """Every variable one node writes."""
    if not isinstance(node, dict):
        return set()
    setter = node.get("set")
    if not isinstance(setter, dict):
        return set()
    return {name for name in setter if isinstance(name, str) and name}


# ---------------------------------------------------------------------
# Graph passes
# ---------------------------------------------------------------------


def _graph_successors(nodes: dict[str, Any], node: Any) -> list[str]:
    """The successors that are real nodes of this tree.

    A pointer at a name that is not in ``nodes`` is dropped, so the branch
    reads as a dead end in the path walk. That pointer already has its own
    ``unknown-target`` error; this keeps it from also reading as a route.
    """
    return [target for target in _successors(node) if target in nodes]


def _reachable(nodes: dict[str, Any], root: str) -> list[str]:
    """Node ids reachable from the root, in sorted order."""
    seen: set[str] = set()
    stack = [root]
    steps = 0
    while stack:
        steps += 1
        if steps > MAX_STEPS:
            break
        nid = stack.pop()
        if nid in seen or nid not in nodes:
            continue
        seen.add(nid)
        for target in _graph_successors(nodes, nodes[nid]):
            if target not in seen:
                stack.append(target)
    return sorted(seen)


def _can_reach(nodes: dict[str, Any], reachable: list[str], seeds: set[str]) -> dict[str, bool]:
    """Whether any of ``seeds`` is reachable at all from each node.

    A least fixpoint: a node turns true once any successor is true. It stops
    changing after at most one pass per node, so a cycle settles instead of
    spinning. This is the compile-time counterpart of the visited set the
    engine uses at run time, and it is what tells a loop that can leave from
    a loop that cannot.
    """
    reaches = {nid: nid in seeds for nid in reachable}
    for _ in range(min(len(reachable) + 2, MAX_STEPS)):
        changed = False
        for nid in reachable:
            if reaches[nid]:
                continue
            if any(reaches.get(s, False) for s in _graph_successors(nodes, nodes[nid])):
                reaches[nid] = True
                changed = True
        if not changed:
            break
    return reaches


def _definitely_set(nodes: dict[str, Any], root: str, reachable: list[str]) -> dict[str, set[str]]:
    """Variables guaranteed written on every path into each node.

    A must-analysis: the entry set of a node is the intersection over its
    predecessors, so a variable written on only one of two branches is not in
    the set after the branches converge. Non-root nodes start at the full set
    of names and shrink, which is what makes a loop settle instead of hang.
    """
    universe: set[str] = set()
    for nid in reachable:
        universe |= _node_vars_writes(nodes[nid])

    preds: dict[str, list[str]] = {nid: [] for nid in reachable}
    for nid in reachable:
        for target in _graph_successors(nodes, nodes[nid]):
            if target in preds:
                preds[target].append(nid)

    entry: dict[str, set[str]] = {
        nid: (set() if nid == root else set(universe)) for nid in reachable
    }
    for _ in range(min(len(reachable) * 2 + 2, MAX_STEPS)):
        changed = False
        for nid in reachable:
            if nid == root:
                continue
            incoming = preds[nid]
            if not incoming:
                new: set[str] = set()
            else:
                new = set.intersection(*(entry[p] | _node_vars_writes(nodes[p]) for p in incoming))
            if new != entry[nid]:
                entry[nid] = new
                changed = True
        if not changed:
            break
    return entry


# ---------------------------------------------------------------------
# Per-rule checks
# ---------------------------------------------------------------------


def _check_shapes_not_mixed(nodes: dict[str, Any], errors: _Collector) -> None:
    outcome_nodes = sorted(nid for nid, node in nodes.items() if kind_of_node(node) == "outcome")
    folding_nodes = sorted(
        nid for nid, node in nodes.items() if kind_of_node(node) in ("register", "stop")
    )
    if not (outcome_nodes and folding_nodes):
        return
    listed_out = ", ".join(repr(nid) for nid in outcome_nodes)
    listed_fold = ", ".join(repr(nid) for nid in folding_nodes)
    errors.add(
        "mixed-shapes",
        f"Outcome leaves {listed_out} sit in the same tree as folding nodes "
        f"{listed_fold}, and one tree may hold only one of the two shapes.",
        f"أوراق النتائج {listed_out} موجودة في نفس الشجرة مع عقد الطي "
        f"{listed_fold}، ولا يمكن لشجرة واحدة أن تحمل إلا أحد الشكلين.",
        *(outcome_nodes + folding_nodes),
    )


def _check_register(
    nid: str, node: dict[str, Any], declared: list[str], errors: _Collector
) -> None:
    register = node.get("register")
    if not isinstance(register, dict):
        errors.add(
            "register-not-a-mapping",
            f"Node {nid!r} 'register' must be a mapping with a code and a severity.",
            f"العقدة {nid!r} يجب أن تكون قيمة 'register' فيها خريطة تحمل رمزاً ودرجة خطورة.",
            nid,
        )
        return
    code = register.get("code")
    if not isinstance(code, str) or not code:
        errors.add(
            "register-without-code",
            f"Node {nid!r} registers a finding with no code.",
            f"العقدة {nid!r} تسجل نتيجة بلا رمز.",
            nid,
        )
    elif code not in declared:
        errors.add(
            "register-not-declared",
            f"Node {nid!r} registers {code!r}, which the tree's 'registers' "
            "list does not declare.",
            f"العقدة {nid!r} تسجل {code!r} وهو غير معلن في قائمة 'registers' الخاصة بالشجرة.",
            nid,
        )
    severity = register.get("severity")
    if severity not in SEVERITIES:
        errors.add(
            "register-bad-severity",
            f"Node {nid!r} has severity {severity!r}, which is not one of "
            f"{', '.join(SEVERITIES)}.",
            f"العقدة {nid!r} درجة خطورتها {severity!r} وهي ليست من {'، '.join(SEVERITIES)}.",
            nid,
        )


def _check_set(nid: str, node: dict[str, Any], errors: _Collector) -> None:
    setter = node.get("set")
    if not isinstance(setter, dict) or not setter:
        errors.add(
            "set-not-a-mapping",
            f"Node {nid!r} 'set' must be a non-empty mapping of variable names to values.",
            f"العقدة {nid!r} يجب أن تكون قيمة 'set' فيها خريطة غير فارغة من أسماء "
            "المتغيرات إلى القيم.",
            nid,
        )
        return
    for name in setter:
        if not isinstance(name, str) or not name:
            errors.add(
                "set-bad-name",
                f"Node {nid!r} writes a variable whose name is not a non-empty string.",
                f"العقدة {nid!r} تكتب متغيراً اسمه ليس نصاً غير فارغ.",
                nid,
            )


def _check_switch(nid: str, node: dict[str, Any], errors: _Collector) -> None:
    switch = node.get("switch")
    if not isinstance(switch, dict):
        errors.add(
            "switch-not-a-mapping",
            f"Node {nid!r} 'switch' must be a mapping with 'on', 'cases' and 'default'.",
            f"العقدة {nid!r} يجب أن تكون قيمة 'switch' فيها خريطة تحمل 'on' و'cases' و'default'.",
            nid,
        )
        return
    if switch.get("on") is None:
        errors.add(
            "switch-without-on",
            f"Node {nid!r} is a switch with nothing to switch on.",
            f"العقدة {nid!r} تبديل بلا قيمة يجري التبديل عليها.",
            nid,
        )
    cases = switch.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.add(
            "switch-without-cases",
            f"Node {nid!r} is a switch with no cases.",
            f"العقدة {nid!r} تبديل بلا حالات.",
            nid,
        )
    else:
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                errors.add(
                    "switch-case-not-a-mapping",
                    f"Node {nid!r} case number {index} must be a mapping.",
                    f"العقدة {nid!r} الحالة رقم {index} يجب أن تكون خريطة.",
                    nid,
                )
                continue
            ops = [key for key in case if key in SWITCH_CASE_OPS]
            if len(ops) != 1:
                errors.add(
                    "switch-case-bad-operator",
                    f"Node {nid!r} case number {index} must name exactly one "
                    f"operator out of {', '.join(sorted(SWITCH_CASE_OPS))}.",
                    f"العقدة {nid!r} الحالة رقم {index} يجب أن تحدد مُعامِلاً واحداً فقط من "
                    f"{'، '.join(sorted(SWITCH_CASE_OPS))}.",
                    nid,
                )
            if not isinstance(case.get("go"), str) or not case["go"]:
                errors.add(
                    "switch-case-without-go",
                    f"Node {nid!r} case number {index} names no node to go to.",
                    f"العقدة {nid!r} الحالة رقم {index} لا تحدد عقدة تنتقل إليها.",
                    nid,
                )
    default = switch.get("default")
    if not isinstance(default, str) or not default:
        errors.add(
            "switch-without-default",
            f"Node {nid!r} is a switch without a 'default', and a switch that "
            "matches no case stops the walk with an error.",
            f"العقدة {nid!r} تبديل بلا 'default'، والتبديل الذي لا يطابق أي حالة "
            "يوقف المسار بخطأ.",
            nid,
        )


def _check_targets(nid: str, node: Any, nodes: dict[str, Any], errors: _Collector) -> None:
    kind = kind_of_node(node)
    if kind in ("register", "set"):
        nxt = node.get("next")
        if not isinstance(nxt, str) or nxt not in nodes:
            errors.add(
                "unknown-target",
                f"Node {nid!r} 'next' points at {nxt!r}, which is not a node in this tree.",
                f"العقدة {nid!r} تشير بـ'next' إلى {nxt!r} وهي ليست عقدة في هذه الشجرة.",
                nid,
            )
        return
    if kind == "condition":
        for branch in ("on_match", "on_miss"):
            target = node.get(branch)
            if not isinstance(target, str) or target not in nodes:
                errors.add(
                    "unknown-target",
                    f"Node {nid!r} {branch!r} points at {target!r}, which is "
                    "not a node in this tree.",
                    f"العقدة {nid!r} تشير بـ{branch!r} إلى {target!r} وهي ليست عقدة "
                    "في هذه الشجرة.",
                    nid,
                )
        return
    if kind == "switch":
        switch = node.get("switch")
        if not isinstance(switch, dict):
            return
        targets: list[Any] = []
        cases = switch.get("cases")
        if isinstance(cases, list):
            targets.extend(case.get("go") for case in cases if isinstance(case, dict))
        if switch.get("default") is not None:
            targets.append(switch.get("default"))
        for target in targets:
            if not isinstance(target, str) or target not in nodes:
                errors.add(
                    "unknown-target",
                    f"Node {nid!r} sends a switch branch to {target!r}, which "
                    "is not a node in this tree.",
                    f"العقدة {nid!r} ترسل أحد فروع التبديل إلى {target!r} وهي ليست عقدة "
                    "في هذه الشجرة.",
                    nid,
                )


def _check_node_bodies(
    nodes: dict[str, Any], declared_registers: list[str], errors: _Collector
) -> None:
    for nid in sorted(nodes):
        node = nodes[nid]
        kind = kind_of_node(node)
        if kind == "unknown":
            errors.add(
                "unknown-node-kind",
                f"Node {nid!r} names no register, set, switch, stop, condition "
                "or outcome, so the engine cannot tell what it does.",
                f"العقدة {nid!r} لا تحدد register أو set أو switch أو stop أو condition "
                "أو outcome، فلا يستطيع المحرك معرفة وظيفتها.",
                nid,
            )
            continue
        if kind == "register":
            _check_register(nid, node, declared_registers, errors)
        elif kind == "set":
            _check_set(nid, node, errors)
        elif kind == "switch":
            _check_switch(nid, node, errors)
        elif kind == "stop" and node.get("stop") is not True:
            errors.add(
                "stop-not-true",
                f"Node {nid!r} must write 'stop: true'.",
                f"العقدة {nid!r} يجب أن تكتب 'stop: true'.",
                nid,
            )
        _check_targets(nid, node, nodes, errors)


def _check_every_path_stops(
    nodes: dict[str, Any], reachable: list[str], errors: _Collector
) -> None:
    # A node that hands the walk nowhere and is not `stop` ends it in the
    # wrong place. Every such node is named, because an author who fixes the
    # first and republishes only to meet the second has learnt nothing.
    dead_ends = [
        nid
        for nid in reachable
        if kind_of_node(nodes[nid]) != "stop" and not _graph_successors(nodes, nodes[nid])
    ]
    if dead_ends:
        listed = ", ".join(repr(nid) for nid in dead_ends)
        errors.add(
            "path-without-stop",
            f"These nodes end the walk without reaching a stop node: {listed}.",
            f"هذه العقد تنهي المسار دون الوصول إلى عقدة stop: {listed}.",
            *dead_ends,
        )

    # A loop that can still leave for `stop` is legal, and a node that can
    # only reach a dead end is already covered above by the dead end it
    # names. What is left is a region the walk can enter and never leave at
    # all, which ends nowhere rather than in the wrong place.
    terminals = {nid for nid in reachable if kind_of_node(nodes[nid]) == "stop"}
    terminals |= set(dead_ends)
    reaches = _can_reach(nodes, reachable, terminals)
    trapped = [nid for nid in reachable if not reaches[nid]]
    if trapped:
        listed = ", ".join(repr(nid) for nid in trapped)
        errors.add(
            "cycle-without-stop",
            f"These nodes loop without ever reaching a stop node: {listed}.",
            f"هذه العقد تدور في حلقة دون الوصول أبداً إلى عقدة stop: {listed}.",
            *trapped,
        )


def _check_vars_reads(
    nodes: dict[str, Any], root: str, reachable: list[str], errors: _Collector
) -> None:
    entry = _definitely_set(nodes, root, reachable)
    for nid in reachable:
        available = entry[nid]
        for name in dict.fromkeys(_node_vars_reads(nodes[nid])):
            if name not in available:
                errors.add(
                    "vars-not-set-on-every-path",
                    f"Node {nid!r} reads variable {name!r}, which is not "
                    "written on every path that reaches it.",
                    f"العقدة {nid!r} تقرأ المتغير {name!r} وهو غير مكتوب على كل مسار " "يصل إليها.",
                    nid,
                )


def _check_registers_block(raw: Any, known_codes: Container[str], errors: _Collector) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.add(
            "registers-not-a-list",
            "The tree's 'registers' block must be a list of finding codes.",
            "يجب أن تكون كتلة 'registers' في الشجرة قائمة من رموز النتائج.",
        )
        return []
    declared: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry:
            errors.add(
                "registers-bad-entry",
                "Every entry in 'registers' must be a non-empty finding code.",
                "يجب أن يكون كل عنصر في 'registers' رمز نتيجة غير فارغ.",
            )
            continue
        if entry not in declared:
            declared.append(entry)
        if entry not in known_codes:
            errors.add(
                "registers-unknown-code",
                f"The tree declares finding code {entry!r}, which is in "
                "neither finding catalogue.",
                f"تعلن الشجرة رمز النتيجة {entry!r} وهو غير موجود في أي من كتالوجي النتائج.",
            )
    return declared


def _check_combinations(
    raw: Any, declared_registers: list[str], errors: _Collector
) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        errors.add(
            "combinations-not-a-list",
            "The tree's 'combinations' block must be a list of rules.",
            "يجب أن تكون كتلة 'combinations' في الشجرة قائمة من القواعد.",
        )
        return []
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for index, rule in enumerate(raw):
        if not isinstance(rule, dict):
            errors.add(
                "combination-not-a-mapping",
                f"Combination rule number {index} must be a mapping.",
                f"قاعدة الدمج رقم {index} يجب أن تكون خريطة.",
            )
            continue
        codes = rule.get("codes")
        if not isinstance(codes, list) or not codes:
            errors.add(
                "combination-without-codes",
                f"Combination rule number {index} lists no finding codes.",
                f"قاعدة الدمج رقم {index} لا تذكر أي رموز نتائج.",
            )
            continue
        bad = [
            code for code in codes if not isinstance(code, str) or code not in declared_registers
        ]
        if bad:
            listed = ", ".join(repr(code) for code in bad)
            errors.add(
                "combination-unknown-code",
                f"Combination rule number {index} uses {listed}, which the "
                "tree's 'registers' list does not declare.",
                f"قاعدة الدمج رقم {index} تستخدم {listed} وهي غير معلنة في قائمة "
                "'registers' الخاصة بالشجرة.",
            )
            continue
        status = rule.get("status")
        if status is not None and status not in FOLDING_STATUSES:
            errors.add(
                "combination-bad-status",
                f"Combination rule number {index} has status {status!r}, "
                f"which is not one of {', '.join(FOLDING_STATUSES)}.",
                f"قاعدة الدمج رقم {index} حالتها {status!r} وهي ليست من "
                f"{'، '.join(FOLDING_STATUSES)}.",
            )
        text_en = rule.get("text_en")
        if not isinstance(text_en, str) or not text_en:
            errors.add(
                "combination-without-text",
                f"Combination rule number {index} has no 'text_en'.",
                f"قاعدة الدمج رقم {index} بلا 'text_en'.",
            )
        # The fold matches on the sorted code set (section 5.1), so two rules
        # over the same set can never both win and one of them is dead text.
        key = tuple(sorted(set(codes)))
        if key in seen_keys:
            errors.add(
                "combination-duplicate-set",
                f"Combination rule number {index} repeats the finding set "
                f"{list(key)}, and only the first would ever be used.",
                f"قاعدة الدمج رقم {index} تكرر مجموعة النتائج {list(key)}، ولن "
                "تُستخدم إلا الأولى.",
            )
        seen_keys.add(key)
        normalized.append(
            {
                "codes": list(key),
                "action_type": rule.get("action_type"),
                "status": status,
                "text_en": text_en,
                "text_ar": rule.get("text_ar"),
            }
        )
    return normalized


# ---------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------


def check_folding_tree(spec: Any, *, known_codes: Container[str]) -> list[CompileError]:
    """Every reason this definition cannot be published, or an empty list.

    ``known_codes`` is the set of finding codes the catalogues resolve. The
    compiler needs nothing else from the catalogue, so it takes the codes
    rather than importing the catalogue module.
    """
    errors = _Collector()

    if not isinstance(spec, dict):
        errors.add(
            "not-a-mapping",
            "The tree definition must be a mapping.",
            "يجب أن يكون تعريف الشجرة خريطة.",
        )
        return errors.errors

    code = spec.get("code")
    if not isinstance(code, str) or not code:
        errors.add("tree-without-code", "The tree has no 'code'.", "الشجرة بلا 'code'.")
    name_en = spec.get("name_en")
    if not isinstance(name_en, str) or not name_en:
        errors.add("tree-without-name", "The tree has no 'name_en'.", "الشجرة بلا 'name_en'.")
    scope = spec.get("scope", "block")
    if scope not in ("block", "cell"):
        errors.add(
            "tree-bad-scope",
            f"The tree 'scope' must be 'block' or 'cell', not {scope!r}.",
            f"يجب أن يكون 'scope' للشجرة 'block' أو 'cell' وليس {scope!r}.",
        )

    nodes = spec.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        errors.add(
            "tree-without-nodes",
            "The tree 'nodes' must be a non-empty mapping.",
            "يجب أن تكون 'nodes' في الشجرة خريطة غير فارغة.",
        )
        return errors.errors
    broken = False
    for nid, node in sorted(nodes.items()):
        if not isinstance(node, dict):
            broken = True
            errors.add(
                "node-not-a-mapping",
                f"Node {nid!r} must be a mapping.",
                f"العقدة {nid!r} يجب أن تكون خريطة.",
                nid,
            )
    if broken:
        return errors.errors

    root = spec.get("root", "root")
    if not isinstance(root, str) or root not in nodes:
        errors.add(
            "tree-bad-root",
            f"The tree 'root' {root!r} is not a node in 'nodes'.",
            f"جذر الشجرة {root!r} ليس عقدة في 'nodes'.",
        )
        return errors.errors

    _check_shapes_not_mixed(nodes, errors)
    declared_registers = _check_registers_block(spec.get("registers"), known_codes, errors)
    _check_node_bodies(nodes, declared_registers, errors)

    # The targeting and parameter blocks keep the rules they have today
    # (``loader.py:226-284``). Their messages are whole-tree, so they name no
    # node.
    try:
        _validate_targeting(spec, "<folding>")
        parameters = _validate_parameters_block(spec, "<folding>")
        _validate_params_refs(nodes, parameters, "<folding>")
        _validate_condition_ops(nodes, "<folding>")
    except DecisionTreeParseError as exc:
        errors.add("invalid-block", exc.reason, exc.reason)

    reachable = _reachable(nodes, root)
    _check_every_path_stops(nodes, reachable, errors)
    _check_vars_reads(nodes, root, reachable, errors)
    _check_combinations(spec.get("combinations"), declared_registers, errors)

    unreached = sorted(set(nodes) - set(reachable))
    if unreached:
        listed = ", ".join(repr(nid) for nid in unreached)
        errors.add(
            "unreachable-node",
            f"These nodes cannot be reached from the root: {listed}.",
            f"لا يمكن الوصول إلى هذه العقد من الجذر: {listed}.",
            *unreached,
        )

    return errors.errors


def compile_folding_tree(spec: dict[str, Any], *, known_codes: Container[str]) -> dict[str, Any]:
    """Validate a folding definition and return its compiled body.

    Raises :class:`FoldingCompileError` holding every problem found.
    """
    errors = check_folding_tree(spec, known_codes=known_codes)
    if errors:
        raise FoldingCompileError(errors)

    crop_paths, country_codes, soil_textures = _validate_targeting(spec, "<folding>")
    parameters = _validate_parameters_block(spec, "<folding>")
    sink = _Collector()
    registers = _check_registers_block(spec.get("registers"), known_codes, sink)
    combinations = _check_combinations(spec.get("combinations"), registers, sink)

    return {
        "shape": "folding",
        "code": spec["code"],
        "name_en": spec["name_en"],
        "name_ar": spec.get("name_ar"),
        "description_en": spec.get("description_en"),
        "description_ar": spec.get("description_ar"),
        "crop_code": spec.get("crop_code"),
        "crop_path": crop_paths[0] if crop_paths else None,
        "crop_paths": crop_paths,
        "country_codes": country_codes,
        "soil_textures": soil_textures,
        "scope": spec.get("scope", "block"),
        "applicable_regions": list(spec.get("applicable_regions") or []),
        "parameters": parameters,
        "registers": registers,
        "combinations": combinations,
        "root": spec.get("root", "root"),
        "nodes": spec["nodes"],
    }


def hash_compiled(compiled: dict[str, Any]) -> str:
    """The content hash of a compiled folding tree."""
    payload = json.dumps(compiled, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
