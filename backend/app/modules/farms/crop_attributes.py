"""Crop attribute resolution and gating — pure, no DB, no I/O.

Definitions live in ``public.crop_attribute_definitions`` and attach at any
level of the crop taxonomy. This module owns the two rules that every
consumer (assignment form, reports, decision-tree context) has to agree on:

1. **Resolution.** For a block's ``crop_path``, walk the path shallow → deep
   and keep the deepest definition per ``code``. A deeper row *replaces* the
   inherited one wholesale — unlike ``default_thresholds``, which shallow-
   merges. Narrowing a range or shortening an option list is only coherent as
   a whole-definition replacement: merging ``{"value_max": 250}`` over a
   definition would leave the inherited options and help text describing a
   range that no longer exists.

2. **Gating.** ``show_when`` / ``required_when`` are one-level, non-recursive
   references to another attribute on the same assignment. Deliberately not an
   expression language: the decision-tree evaluator already is one, and a
   second one here would have to be taught to every consumer.

Keeping both pure means the assignment form, the report column resolver and
the decision-tree context loader can each batch-load rows once and agree on
the outcome without a round trip.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

VALUE_TYPES: tuple[str, ...] = (
    "integer",
    "decimal",
    "text",
    "boolean",
    "date",
    "single_select",
    "multi_select",
)
NUMERIC_VALUE_TYPES: frozenset[str] = frozenset({"integer", "decimal"})
SELECT_VALUE_TYPES: frozenset[str] = frozenset({"single_select", "multi_select"})

# Types a gate may point at. A gate on a free-text or numeric field would be a
# string/number equality test that no author can reason about from the form, and
# it is never what the establishment-method case needs.
GATEABLE_VALUE_TYPES: frozenset[str] = frozenset({"single_select", "boolean"})

# Codes an attribute may not claim.
#
# `block_crops` already carries these as real columns, and the decision-tree
# `block` source already exposes the second group. An attribute reusing one of
# these codes would shadow a first-class field in the condition builder's
# dropdown — two entries reading "growth stage", one of them always None —
# and there is no error anywhere to notice it. Rejected at authoring time.
RESERVED_ATTRIBUTE_CODES: frozenset[str] = frozenset(
    {
        # block_crops columns
        "season_label",
        "planting_date",
        "expected_harvest_start",
        "expected_harvest_end",
        "actual_harvest_date",
        "plant_density_per_ha",
        "row_spacing_m",
        "plant_spacing_m",
        "canopy_size_class",
        "growth_stage",
        "is_current",
        "status",
        "notes",
        "crop_path",
        # conditions BLOCK_FIELDS (app/shared/conditions/models.py)
        "crop_category",
        "crop_strain",
        "soil_texture",
        "salinity_class",
    }
)


class DefinitionLike(Protocol):
    """The shape :func:`resolve_definitions` needs.

    A Protocol rather than the ORM class so tests can pass plain objects and
    the report/DT paths can pass lightweight row tuples.
    """

    path: str
    code: str
    sort_order: int
    is_active: bool


@dataclass(frozen=True, slots=True)
class Resolution:
    """Outcome of a deepest-wins walk.

    ``shadowed`` is not decoration: the platform authoring UI has to show that
    a crop-level definition is being replaced deeper down, or an author edits
    the crop row and sees nothing change for the variety they were looking at.
    """

    definitions: list[Any]
    shadowed: list[Any]


def path_prefixes(crop_path: str) -> list[str]:
    """``"mango.alphonso.short"`` → ``["mango", "mango.alphonso", "mango.alphonso.short"]``.

    >>> path_prefixes("mango.sukkary")
    ['mango', 'mango.sukkary']
    >>> path_prefixes("")
    []
    """
    segments = [s for s in crop_path.split(".") if s]
    return [".".join(segments[: i + 1]) for i in range(len(segments))]


def resolve_definitions(
    definitions: Iterable[Any],
    *,
    crop_path: str,
    include_inactive: bool = False,
) -> Resolution:
    """Deepest-wins by ``code`` along ``crop_path``.

    ``definitions`` may contain rows for unrelated paths (callers batch-load
    per crop); anything not on the path is ignored. Ordering is
    ``(sort_order, code)`` so two definitions that forgot to set a distinct
    ``sort_order`` still render deterministically.

    Inactive rows participate in the walk before being dropped, which is what
    makes suppression work: a variety-level row with ``is_active = false``
    shadows the crop-level definition and then removes itself.
    """
    depth_of = {prefix: depth for depth, prefix in enumerate(path_prefixes(crop_path))}
    winner: dict[str, Any] = {}
    winner_depth: dict[str, int] = {}
    shadowed: list[Any] = []

    for definition in definitions:
        depth = depth_of.get(definition.path)
        if depth is None:
            continue
        current_depth = winner_depth.get(definition.code)
        if current_depth is None:
            winner[definition.code] = definition
            winner_depth[definition.code] = depth
        elif depth > current_depth:
            shadowed.append(winner[definition.code])
            winner[definition.code] = definition
            winner_depth[definition.code] = depth
        else:
            # Same depth is impossible (unique on (path, code)); shallower
            # means the caller handed us rows out of order.
            shadowed.append(definition)

    resolved = [d for d in winner.values() if include_inactive or getattr(d, "is_active", True)]
    resolved.sort(key=lambda d: (d.sort_order, d.code))
    return Resolution(definitions=resolved, shadowed=shadowed)


def gate_matches(gate: Mapping[str, Any] | None, values: Mapping[str, Any]) -> bool:
    """Evaluate one ``{"code": ..., "in": [...] | "eq": ...}`` gate.

    Returns ``False`` for a ``None`` gate — callers decide what absence means
    (``show_when`` absent → always shown; ``required_when`` absent → never
    required), and conflating those two defaults is how a field ends up
    silently mandatory.

    >>> gate_matches({"code": "m", "in": ["a", "b"]}, {"m": "b"})
    True
    >>> gate_matches({"code": "m", "eq": "a"}, {"m": "b"})
    False
    >>> gate_matches({"code": "m", "in": ["a"]}, {})
    False
    """
    if not gate:
        return False
    code = gate.get("code")
    if not code or code not in values:
        return False
    actual = values[code]
    if "in" in gate:
        allowed = gate["in"]
        if isinstance(actual, list | tuple | set):
            return any(item in allowed for item in actual)
        return actual in allowed
    if "eq" in gate:
        return actual == gate["eq"]
    return False


def normalize_gate(gate: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Drop unset operands so a stored gate is exactly what it means.

    Pydantic dumps the whole model, so a gate authored with ``in`` also
    carries ``"eq": None``. Persisting that leaves a JSONB blob whose shape
    differs from what a hand-written seed migration produces, and every
    consumer then has to know that ``eq: null`` means "no eq" rather than
    "equals null".

    >>> normalize_gate({"code": "m", "in": ["a"], "eq": None})
    {'code': 'm', 'in': ['a']}
    >>> normalize_gate({"code": "m", "in": None, "eq": False})
    {'code': 'm', 'eq': False}
    """
    if gate is None:
        return None
    return {k: v for k, v in gate.items() if v is not None}


def is_visible(definition: Any, values: Mapping[str, Any]) -> bool:
    """A definition with no ``show_when`` is always shown."""
    gate = getattr(definition, "show_when", None)
    if not gate:
        return True
    return gate_matches(gate, values)


def is_required(definition: Any, values: Mapping[str, Any]) -> bool:
    """Unconditionally required, or required by an open ``required_when`` gate.

    Only meaningful for a *visible* definition — a hidden field is never
    required, and callers must check :func:`is_visible` first.
    """
    if getattr(definition, "is_required", False):
        return True
    return gate_matches(getattr(definition, "required_when", None), values)


def visible_definitions(definitions: Sequence[Any], values: Mapping[str, Any]) -> list[Any]:
    """The subset of ``definitions`` whose gates are open for ``values``."""
    return [d for d in definitions if is_visible(d, values)]


# Which typed column each value_type lands in. One mapping, used by the write
# path, the read path, the report resolver and the decision-tree context —
# a second copy is how a value gets written to one column and read from
# another, which reads as "the field didn't save".
VALUE_COLUMN_BY_TYPE: dict[str, str] = {
    "integer": "value_numeric",
    "decimal": "value_numeric",
    "text": "value_text",
    "boolean": "value_boolean",
    "date": "value_date",
    "single_select": "value_option",
    "multi_select": "value_options",
}


def _coerce_number(definition: Any, raw: Any) -> Decimal:
    code = definition.code
    try:
        number = Decimal(str(raw))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"{code}: {raw!r} is not a number") from exc
    if definition.value_type == "integer" and number != number.to_integral_value():
        raise ValueError(f"{code}: must be a whole number")
    minimum = getattr(definition, "value_min", None)
    maximum = getattr(definition, "value_max", None)
    if minimum is not None and number < Decimal(str(minimum)):
        raise ValueError(f"{code}: {number} is below the minimum {minimum}")
    if maximum is not None and number > Decimal(str(maximum)):
        raise ValueError(f"{code}: {number} is above the maximum {maximum}")
    return number


def _coerce_date(definition: Any, raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ValueError(f"{definition.code}: {raw!r} is not an ISO date (YYYY-MM-DD)") from exc


def _coerce_text(definition: Any, raw: Any) -> str:
    value = str(raw)
    limit = getattr(definition, "text_max_length", None) or 500
    if len(value) > limit:
        raise ValueError(f"{definition.code}: longer than {limit} characters")
    return value


def _coerce_boolean(definition: Any, raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    raise ValueError(f"{definition.code}: expected true or false")


def _option_codes(definition: Any) -> set[Any]:
    return {_option_code(o) for o in (getattr(definition, "options", None) or [])}


def _coerce_single_select(definition: Any, raw: Any) -> str:
    allowed = _option_codes(definition)
    if raw not in allowed:
        raise ValueError(f"{definition.code}: {raw!r} is not one of {sorted(allowed)}")
    return str(raw)


def _coerce_multi_select(definition: Any, raw: Any) -> list[str] | None:
    if not isinstance(raw, list | tuple):
        raise ValueError(f"{definition.code}: expected a list of option codes")
    allowed = _option_codes(definition)
    chosen = list(dict.fromkeys(raw))
    unknown = [v for v in chosen if v not in allowed]
    if unknown:
        raise ValueError(f"{definition.code}: {unknown!r} are not options of this attribute")
    # An empty selection is an absent value, not an empty array — see the
    # options_non_empty CHECK in tenant migration 0055.
    return [str(v) for v in chosen] or None


_COERCERS: dict[str, Any] = {
    "integer": _coerce_number,
    "decimal": _coerce_number,
    "text": _coerce_text,
    "boolean": _coerce_boolean,
    "date": _coerce_date,
    "single_select": _coerce_single_select,
    "multi_select": _coerce_multi_select,
}


def coerce_value(definition: Any, raw: Any) -> Any:
    """Validate + coerce one submitted value against its definition.

    Returns the Python object to bind to the typed column — ``Decimal`` for
    numerics, ``date`` for dates, ``list[str]`` for multi-select — never a
    string standing in for one. Passing an ISO string through a
    ``CAST(:x AS date)`` is precisely the bug that took the backfill console
    down (#331), so the coercion happens here, once, in typed Python.

    Raises ``ValueError`` with a message naming the attribute.
    """
    if raw is None or raw == "":
        return None
    coercer = _COERCERS.get(definition.value_type)
    if coercer is None:
        raise ValueError(f"{definition.code}: unknown value_type {definition.value_type!r}")
    return coercer(definition, raw)


def _option_code(option: Any) -> Any:
    """Options arrive as Pydantic models on create and as JSONB dicts on update."""
    return option.get("code") if isinstance(option, Mapping) else getattr(option, "code", None)


def validate_type_consistency(
    *,
    value_type: str,
    options: Sequence[Any] | None = None,
    value_min: Any = None,
    value_max: Any = None,
    decimal_places: int | None = None,
    unit_en: str | None = None,
    unit_ar: str | None = None,
    text_max_length: int | None = None,
) -> None:
    """Cross-field rules the DB CHECKs can't express. Raises ``ValueError``.

    One implementation, two callers: the create schema (so an author gets a
    422 naming the field) and the update service (so a PATCH can't reach a
    state the create path would have rejected — ``value_type`` is immutable,
    so the stored type is merged in before checking). Duplicating these rules
    per call site is how a validator ends up enforced on POST and not PATCH.
    """
    if value_type not in VALUE_TYPES:
        raise ValueError(f"unknown value_type {value_type!r}")

    is_select = value_type in SELECT_VALUE_TYPES
    if is_select and not options:
        raise ValueError(f"{value_type} requires a non-empty 'options' list")
    if not is_select and options:
        raise ValueError(f"'options' is only valid for select types, not {value_type}")
    if options:
        codes = [_option_code(o) for o in options]
        if len(set(codes)) != len(codes):
            raise ValueError("option codes must be unique")

    is_numeric = value_type in NUMERIC_VALUE_TYPES
    if not is_numeric and any(
        v is not None for v in (value_min, value_max, decimal_places, unit_en, unit_ar)
    ):
        raise ValueError(
            "value_min/value_max/decimal_places/unit_* are only valid for "
            f"integer and decimal, not {value_type}"
        )
    if value_min is not None and value_max is not None and value_min > value_max:
        raise ValueError("value_min must be <= value_max")
    if value_type == "integer" and decimal_places:
        raise ValueError("decimal_places is not valid for an integer attribute")
    if text_max_length is not None and value_type != "text":
        raise ValueError(f"text_max_length is only valid for text, not {value_type}")
    # Both units or neither: a unit rendered in one language only is worse than
    # no unit, because the Arabic form silently drops it.
    if (unit_en is None) != (unit_ar is None):
        raise ValueError("unit_en and unit_ar must be provided together")
