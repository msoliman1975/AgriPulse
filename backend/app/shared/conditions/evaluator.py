"""Recursive condition-tree evaluator.

Tree dialect (subset of JSON Logic, deliberately small):

  Boolean nodes — exactly one key:
    {"all_of": [<child>, <child>, ...]}      # AND, vacuous → True
    {"any_of": [<child>, <child>, ...]}      # OR,  vacuous → False
    {"not":     <child>}                      # NOT

  Comparison nodes — ``op`` key drives shape:
    {"op": "lt"|"le"|"gt"|"ge"|"eq"|"ne", "left": <ref>, "right": <literal>}
    {"op": "between", "left": <ref>, "low": <literal>, "high": <literal>}
    {"op": "in",      "left": <ref>, "values": [<literal>, ...]}

A reference resolving to ``None`` (signal not yet observed, etc.)
short-circuits the *comparison* to False; this matches the existing
alert-predicate behavior and keeps a half-loaded tenant from spuriously
firing on missing data.

Snapshot shape (returned alongside the boolean):

  {"tree_match": <bool>,
   "values":     {"<dotted-ref>": "<resolved-as-string>"}}

Dotted refs use the canonical form so two rules referencing the same
signal collide deterministically — e.g.
``"indices.ndvi.baseline_deviation"``. Decimals are stringified to
preserve precision through the JSONB roundtrip.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from app.shared.conditions.context import ConditionContext
from app.shared.conditions.errors import ConditionParseError
from app.shared.conditions.models import (
    BlockValueRef,
    IndicesValueRef,
    ParamsValueRef,
    SignalsValueRef,
    ValueRef,
    WeatherValueRef,
    parse_value_ref,
)

_COMPARABLE_OPS = ("lt", "le", "gt", "ge", "eq", "ne")


def evaluate(tree: Any, ctx: ConditionContext) -> tuple[bool, dict[str, Any]]:
    """Walk ``tree`` against ``ctx``; return ``(matched, snapshot)``.

    Permissive: any parse error or unknown node returns
    ``(False, {"tree_match": False})`` rather than raising.
    """
    snapshot: dict[str, Any] = {"values": {}}
    try:
        matched = _eval_node(tree, ctx, snapshot)
    except ConditionParseError:
        snapshot["tree_match"] = False
        snapshot["values"] = {}
        return False, snapshot
    snapshot["tree_match"] = matched
    return matched, snapshot


def _eval_node(node: Any, ctx: ConditionContext, snapshot: dict[str, Any]) -> bool:
    if not isinstance(node, Mapping):
        raise ConditionParseError(f"node must be an object, got {type(node).__name__}")

    if "all_of" in node:
        children = node["all_of"]
        if not isinstance(children, list):
            raise ConditionParseError("'all_of' must be a list")
        return all(_eval_node(c, ctx, snapshot) for c in children)

    if "any_of" in node:
        children = node["any_of"]
        if not isinstance(children, list):
            raise ConditionParseError("'any_of' must be a list")
        return any(_eval_node(c, ctx, snapshot) for c in children)

    if "not" in node:
        return not _eval_node(node["not"], ctx, snapshot)

    if "op" in node:
        return _eval_comparison(node, ctx, snapshot)

    raise ConditionParseError(f"unknown node keys: {sorted(node.keys())}")


def _eval_comparison(
    node: Mapping[str, Any], ctx: ConditionContext, snapshot: dict[str, Any]
) -> bool:
    op = node.get("op")
    ref = parse_value_ref(node.get("left"))
    left = _resolve(ref, ctx)
    snapshot["values"][_ref_key(ref)] = _stringify(left)

    if left is None:
        return False  # missing data → does not match

    if op in _COMPARABLE_OPS:
        right_raw = node.get("right")
        if right_raw is None:
            raise ConditionParseError(f"op '{op}' requires 'right'")
        right = _resolve_literal_or_ref(right_raw, ctx, snapshot)
        # A right-side ref that doesn't resolve (e.g. a missing
        # parameter) short-circuits to no-match, same as left-side.
        if right is None:
            return False
        return _compare(op, left, right)

    if op == "between":
        low_raw = node.get("low")
        high_raw = node.get("high")
        if low_raw is None or high_raw is None:
            raise ConditionParseError("op 'between' requires 'low' and 'high'")
        low = _resolve_literal_or_ref(low_raw, ctx, snapshot)
        high = _resolve_literal_or_ref(high_raw, ctx, snapshot)
        if low is None or high is None:
            return False
        return _compare("ge", left, low) and _compare("le", left, high)

    if op == "in":
        values = node.get("values")
        if not isinstance(values, list):
            raise ConditionParseError("op 'in' requires 'values' list")
        resolved = [_resolve_literal_or_ref(v, ctx, snapshot) for v in values]
        return any(_compare("eq", left, v) for v in resolved if v is not None)

    raise ConditionParseError(f"unknown op {op!r}")


def _resolve_literal_or_ref(
    value: Any, ctx: ConditionContext, snapshot: dict[str, Any]
) -> Any:
    """If ``value`` is a value-ref dict (has a ``source`` key), resolve
    it against the context; otherwise return it as a literal.

    Snapshot recording: ref-typed right/low/high values are recorded
    under their dotted key the same way left-side refs are, so the
    explainability trail shows the resolved parameter / weather value
    that the comparison actually used.
    """
    if isinstance(value, dict) and "source" in value:
        ref = parse_value_ref(value)
        resolved = _resolve(ref, ctx)
        snapshot["values"][_ref_key(ref)] = _stringify(resolved)
        return resolved
    return value


def _resolve(  # noqa: PLR0911 - dispatch over ValueRef kinds
    ref: ValueRef, ctx: ConditionContext
) -> Any:
    if isinstance(ref, IndicesValueRef):
        idx_entry = ctx.indices.get(ref.index_code)
        if idx_entry is None:
            return None
        return getattr(idx_entry, ref.key, None)
    if isinstance(ref, BlockValueRef):
        if ref.field == "crop_category":
            return ctx.crop_category
        return ctx.block_attributes.get(ref.field)
    if isinstance(ref, WeatherValueRef):
        if ctx.weather is None:
            return None
        scope_dict = getattr(ctx.weather, ref.scope, None)
        if scope_dict is None:
            return None
        return scope_dict.get(ref.field)
    if isinstance(ref, SignalsValueRef):
        sig_entry = ctx.signals.get(ref.code)
        if sig_entry is None:
            return None
        return getattr(sig_entry, ref.key, None)
    if isinstance(ref, ParamsValueRef):
        return ctx.params.get(ref.name)
    return None


def _ref_key(ref: ValueRef) -> str:
    if isinstance(ref, IndicesValueRef):
        return f"indices.{ref.index_code}.{ref.key}"
    if isinstance(ref, WeatherValueRef):
        return f"weather.{ref.scope}.{ref.field}"
    if isinstance(ref, SignalsValueRef):
        return f"signals.{ref.code}.{ref.key}"
    if isinstance(ref, ParamsValueRef):
        return f"params.{ref.name}"
    return f"block.{ref.field}"


_COMPARE_FNS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: bool(a == b),
    "ne": lambda a, b: bool(a != b),
    "lt": lambda a, b: bool(a < b),
    "le": lambda a, b: bool(a <= b),
    "gt": lambda a, b: bool(a > b),
    "ge": lambda a, b: bool(a >= b),
}


def _compare(op: str, left: Any, right: Any) -> bool:
    """Compare two values, coercing through Decimal when both look numeric."""
    fn = _COMPARE_FNS.get(op)
    if fn is None:
        raise ConditionParseError(f"unknown comparison op {op!r}")
    lhs, rhs = _coerce_pair(left, right)
    try:
        return fn(lhs, rhs)
    except TypeError:
        # Ordering ops on incomparable types (e.g. str vs int) fall to False.
        return False


def _coerce_pair(left: Any, right: Any) -> tuple[Any, Any]:
    """If both sides look numeric, coerce to Decimal for stable compare."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left, right
    if _looks_numeric(left) and _looks_numeric(right):
        return _to_decimal(left), _to_decimal(right)
    return left, right


def _looks_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float | Decimal):
        return True
    if isinstance(value, str):
        try:
            Decimal(value)
        except (ValueError, ArithmeticError):
            return False
        return True
    return False


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _stringify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
