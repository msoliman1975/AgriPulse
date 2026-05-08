"""Typed value references for the condition tree.

The tree itself is dict-shaped JSON; ``parse_value_ref`` is a small
strict parser that turns the leaf ``{"source": ..., ...}`` dicts into
typed dataclasses for the evaluator. Tree nodes (``all_of`` / ``any_of``
/ ``not`` / comparison ops) stay as dicts and are walked recursively —
no pydantic gymnastics for variants that are mutually disambiguated by
key presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.shared.conditions.errors import ConditionParseError

INDICES_KEYS: tuple[str, ...] = ("mean", "baseline_deviation")
BLOCK_FIELDS: tuple[str, ...] = ("crop_category",)


@dataclass(frozen=True, slots=True)
class IndicesValueRef:
    """``{"source":"indices","index_code":"ndvi","key":"baseline_deviation"}``"""

    source: Literal["indices"]
    index_code: str
    key: str  # one of INDICES_KEYS


@dataclass(frozen=True, slots=True)
class BlockValueRef:
    """``{"source":"block","field":"crop_category"}``"""

    source: Literal["block"]
    field: str  # one of BLOCK_FIELDS


ValueRef = IndicesValueRef | BlockValueRef


def parse_value_ref(raw: Any) -> ValueRef:
    """Strict parse of a leaf value-ref dict.

    Raises ``ConditionParseError`` on unknown source or missing/invalid
    fields. The evaluator catches and treats parse errors as
    ``(False, {})`` per the permissive-on-malformed contract.
    """
    if not isinstance(raw, dict):
        raise ConditionParseError(f"value ref must be an object, got {type(raw).__name__}")
    source = raw.get("source")
    if source == "indices":
        index_code = raw.get("index_code")
        if not isinstance(index_code, str) or not index_code:
            raise ConditionParseError("indices ref missing 'index_code'")
        key = raw.get("key", "baseline_deviation")
        if key not in INDICES_KEYS:
            raise ConditionParseError(f"indices ref 'key' must be one of {INDICES_KEYS}")
        return IndicesValueRef(source="indices", index_code=index_code, key=key)
    if source == "block":
        field_ = raw.get("field")
        if field_ not in BLOCK_FIELDS:
            raise ConditionParseError(f"block ref 'field' must be one of {BLOCK_FIELDS}")
        return BlockValueRef(source="block", field=field_)
    raise ConditionParseError(f"unknown value-ref source {source!r}")
