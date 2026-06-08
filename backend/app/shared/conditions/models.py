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

from app.shared.conditions.context import GRID_FIELDS, SIGNAL_KEYS, WEATHER_SCOPES
from app.shared.conditions.errors import ConditionParseError

# ``slope`` / ``delta`` / ``trend_direction`` (KB P2) are precomputed by
# the context-builder from the recent aggregate history (indices/trends.py).
# ``trend_direction`` is categorical (rising/falling/stable) — compare with
# eq/ne/in; ``slope``/``delta`` are numeric. They let a rule express
# "NDMI decreasing" without any temporal operator in the evaluator.
INDICES_KEYS: tuple[str, ...] = (
    "mean",
    "baseline_deviation",
    "slope",
    "delta",
    "trend_direction",
)
# ``growth_stage`` (KB P3) is the stored phenological stage on the block's
# current block_crops row (categorical, e.g. tuber_bulking). Compare with
# eq/ne/in. Resolves via ``block_attributes`` and is None until a stage is
# set, so stage-gated rules fail closed.
BLOCK_FIELDS: tuple[str, ...] = ("crop_category", "growth_stage")


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


@dataclass(frozen=True, slots=True)
class WeatherValueRef:
    """``{"source":"weather","scope":"forecast_24h","field":"precipitation_mm_total"}``

    ``scope`` selects which dict in ``WeatherSnapshot`` to read from
    (latest_observation / forecast_24h / forecast_72h / derived_today /
    derived_yesterday). ``field`` is the key inside that dict — not
    pre-validated, since the loader is the source of truth for which
    fields exist per scope. A misspelled field resolves to ``None``,
    which is permissive-on-missing-data.
    """

    source: Literal["weather"]
    scope: str  # one of WEATHER_SCOPES
    field: str


@dataclass(frozen=True, slots=True)
class SignalsValueRef:
    """``{"source":"signals","code":"soil_moisture","key":"value_numeric"}``

    ``code`` is the tenant-scoped ``signal_definitions.code`` —
    matched against the snapshot's keys. ``key`` defaults to
    ``value_numeric`` (the most common predicate target) and must be
    one of ``SIGNAL_KEYS``.
    """

    source: Literal["signals"]
    code: str
    key: str  # one of SIGNAL_KEYS


@dataclass(frozen=True, slots=True)
class GridValueRef:
    """``{"source":"grid","index_code":"ndvi","field":"flagged_count"}``

    Reads the latest sub-block grid spatial-anomaly verdict for ``index_code``
    (G-4). ``field`` is one of ``GRID_FIELDS`` (worst_z / flagged_count /
    worst_row / worst_col / severity). Resolves to ``None`` — fail-closed —
    when the block has no current anomaly for that index, matching every
    other source. Only valid on a comparison ``left`` (observed data).
    """

    source: Literal["grid"]
    index_code: str
    field: str  # one of GRID_FIELDS


@dataclass(frozen=True, slots=True)
class ParamsValueRef:
    """``{"source":"params","name":"ndvi_drop_threshold"}``

    Resolves to a decision-tree parameter value (defaults from the
    tree's ``parameters:`` declaration, layered with tenant overrides
    in PR-C). Used in any literal slot of a comparison node:
    ``right`` / ``low`` / ``high`` / inside ``values``. NOT valid on
    a comparison ``left``, which always points at observed data.

    Permissive resolution: unknown name → None → comparison fails
    closed, matching every other ref kind.
    """

    source: Literal["params"]
    name: str


ValueRef = (
    IndicesValueRef
    | BlockValueRef
    | WeatherValueRef
    | SignalsValueRef
    | GridValueRef
    | ParamsValueRef
)


def parse_value_ref(raw: Any) -> ValueRef:  # noqa: PLR0912 - dispatch over ref sources
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
    if source == "weather":
        scope = raw.get("scope")
        if scope not in WEATHER_SCOPES:
            raise ConditionParseError(f"weather ref 'scope' must be one of {WEATHER_SCOPES}")
        field_ = raw.get("field")
        if not isinstance(field_, str) or not field_:
            raise ConditionParseError("weather ref missing 'field'")
        return WeatherValueRef(source="weather", scope=scope, field=field_)
    if source == "signals":
        code = raw.get("code")
        if not isinstance(code, str) or not code:
            raise ConditionParseError("signals ref missing 'code'")
        key = raw.get("key", "value_numeric")
        if key not in SIGNAL_KEYS:
            raise ConditionParseError(f"signals ref 'key' must be one of {SIGNAL_KEYS}")
        return SignalsValueRef(source="signals", code=code, key=key)
    if source == "grid":
        index_code = raw.get("index_code")
        if not isinstance(index_code, str) or not index_code:
            raise ConditionParseError("grid ref missing 'index_code'")
        field_ = raw.get("field")
        if field_ not in GRID_FIELDS:
            raise ConditionParseError(f"grid ref 'field' must be one of {GRID_FIELDS}")
        return GridValueRef(source="grid", index_code=index_code, field=field_)
    if source == "params":
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ConditionParseError("params ref missing 'name'")
        return ParamsValueRef(source="params", name=name)
    raise ConditionParseError(f"unknown value-ref source {source!r}")
