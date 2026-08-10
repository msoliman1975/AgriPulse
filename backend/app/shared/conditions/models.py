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

from app.shared.conditions.context import (
    CROP_ATTRIBUTE_KEYS,
    GRID_FIELDS,
    SIGNAL_KEYS,
    WEATHER_INDEX_KEYS,
    WEATHER_RISK_FIELDS,
    WEATHER_SCOPES,
)
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
# ``soil_texture`` (sandy/loam/clay variants) + ``salinity_class`` come from
# the block.
#
# Three identity fields were removed from this vocabulary: ``crop_category``,
# ``crop_path`` and ``crop_strain``. All three restate the tree's own targeting
# — a tree already declares which crop paths it runs on, and crop_category is
# just the catalog's grouping of that same crop — so branching on them inside
# the tree asks a question the targeting has already answered. No tree in the
# catalog ever used one in a condition. ``crop_path`` is still loaded and still
# drives targeting and the crop stamped on each recommendation; it simply is no
# longer something a *condition* can read.
BLOCK_FIELDS: tuple[str, ...] = (
    "growth_stage",
    "soil_texture",
    "salinity_class",
)


@dataclass(frozen=True, slots=True)
class IndicesValueRef:
    """``{"source":"indices","index_code":"ndvi","key":"baseline_deviation"}``"""

    source: Literal["indices"]
    index_code: str
    key: str  # one of INDICES_KEYS


@dataclass(frozen=True, slots=True)
class BlockValueRef:
    """``{"source":"block","field":"growth_stage"}``"""

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
class WeatherIndexValueRef:
    """``{"source":"weather_index","index_code":"temperature","key":"baseline_deviation"}``

    Reads a *farm-level* first-class weather index (PR-W7) — the latest
    ``weather_index_daily`` row for ``index_code``. ``key`` is one of
    ``WEATHER_INDEX_KEYS`` (``value`` or ``baseline_deviation``); it
    defaults to ``baseline_deviation`` (the z-score versus the day-of-year
    climatology) so the common predicate is anomaly-first, mirroring
    ``indices``. Unlike ``weather`` (raw snapshot fields), this exposes the
    curated index family with built-in anomaly scoring. Resolves to
    ``None`` — fail-closed — when the farm has no projected row for that
    index, matching every other source.
    """

    source: Literal["weather_index"]
    index_code: str
    key: str  # one of WEATHER_INDEX_KEYS


@dataclass(frozen=True, slots=True)
class WeatherRiskValueRef:
    """``{"source":"weather_risk","risk_code":"powdery_mildew","field":"score"}``

    Reads a *per-block* weather-driven disease/pest risk (PR-R3) — the latest
    ``weather_risk_daily`` row for ``risk_code``. ``field`` is one of
    ``WEATHER_RISK_FIELDS``: ``score`` (the 0-100 pressure, the default) or
    ``level`` (``low``/``moderate``/``high``, compared with eq/ne). Unlike
    ``weather_index`` (farm-level), risk folds in the block's crop + growth
    stage, so it is the spatial source. Resolves to ``None`` — fail-closed —
    when the block has no scored row for that pathogen, matching every other
    source.
    """

    source: Literal["weather_risk"]
    risk_code: str
    field: str  # one of WEATHER_RISK_FIELDS


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


@dataclass(frozen=True, slots=True)
class CropAttributeValueRef:
    """``{"source":"crop_attribute","code":"age_at_transplant_months","key":"value"}``

    Reads a platform-curated crop attribute recorded on the block's *current*
    crop assignment — establishment method, transplant date, age at
    transplant, seed-tuber grade, and whatever else the catalog defines for
    that crop.

    Unlike every other source, the set of valid ``code`` values is **data**,
    not a constant: it comes from ``public.crop_attribute_definitions`` and
    grows as the catalog does. So ``code`` is not validated against a closed
    list here — an unknown code resolves to ``None`` and the comparison fails
    closed, matching ``weather``'s treatment of ``field``. The authoring-time
    check that a tree's referenced codes exist for its target crop paths lives
    in the tree validator, where the targeting is known.

    ``key`` is ``value`` (the only key today; declared as a list so a future
    ``days_since`` derivation can be added without changing the ref shape).
    The resolved Python type follows the definition's ``value_type``:
    ``Decimal`` for numerics, ``date`` for dates, ``str`` for text and
    single-select, ``list[str]`` for multi-select — so a multi-select is
    only meaningfully compared with ``in`` / ``eq`` / ``ne``.
    """

    source: Literal["crop_attribute"]
    code: str
    key: str  # one of CROP_ATTRIBUTE_KEYS


ValueRef = (
    IndicesValueRef
    | BlockValueRef
    | WeatherValueRef
    | WeatherIndexValueRef
    | WeatherRiskValueRef
    | SignalsValueRef
    | GridValueRef
    | CropAttributeValueRef
    | ParamsValueRef
)


def parse_value_ref(raw: Any) -> ValueRef:  # noqa: PLR0911, PLR0912, PLR0915 - dispatch
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
    if source == "weather_index":
        index_code = raw.get("index_code")
        if not isinstance(index_code, str) or not index_code:
            raise ConditionParseError("weather_index ref missing 'index_code'")
        key = raw.get("key", "baseline_deviation")
        if key not in WEATHER_INDEX_KEYS:
            raise ConditionParseError(
                f"weather_index ref 'key' must be one of {WEATHER_INDEX_KEYS}"
            )
        return WeatherIndexValueRef(source="weather_index", index_code=index_code, key=key)
    if source == "weather_risk":
        risk_code = raw.get("risk_code")
        if not isinstance(risk_code, str) or not risk_code:
            raise ConditionParseError("weather_risk ref missing 'risk_code'")
        field_ = raw.get("field", "score")
        if field_ not in WEATHER_RISK_FIELDS:
            raise ConditionParseError(
                f"weather_risk ref 'field' must be one of {WEATHER_RISK_FIELDS}"
            )
        return WeatherRiskValueRef(source="weather_risk", risk_code=risk_code, field=field_)
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
    if source == "crop_attribute":
        code = raw.get("code")
        if not isinstance(code, str) or not code:
            raise ConditionParseError("crop_attribute ref missing 'code'")
        key = raw.get("key", "value")
        if key not in CROP_ATTRIBUTE_KEYS:
            raise ConditionParseError(
                f"crop_attribute ref 'key' must be one of {CROP_ATTRIBUTE_KEYS}"
            )
        return CropAttributeValueRef(source="crop_attribute", code=code, key=key)
    if source == "params":
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ConditionParseError("params ref missing 'name'")
        return ParamsValueRef(source="params", name=name)
    raise ConditionParseError(f"unknown value-ref source {source!r}")
