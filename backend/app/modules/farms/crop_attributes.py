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
