"""Pre-loaded data the evaluator reads from.

The service layer (alerts engine driver, recommendations evaluator)
loads a ``ConditionContext`` once per block per evaluation pass and
hands it to ``evaluate``. Adding a new source means adding a field
here and teaching the relevant value-ref resolver to read it; the
evaluator core stays untouched.

Currently wired sources: ``indices`` (NDVI / EVI / etc. aggregates),
``block`` (growth stage, soil texture, salinity class), and ``weather``
(latest observation, near-term forecast windows, derived daily). The
``signals`` source is still unbuilt — rules that reference it return
``(False, {})`` per the permissive-on-missing-data contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Allowed keys for a weather-index value-ref. ``value`` is the farm-level
# daily index value (temperature / radiation / evapotranspiration / …);
# ``baseline_deviation`` is its z-score against the day-of-year climatology
# baseline — the anomaly-first key, mirroring ``indices``. Both are None
# when the farm has no projected ``weather_index_daily`` row yet, so a
# predicate fails closed.
WEATHER_INDEX_KEYS: tuple[str, ...] = (
    "value",
    "baseline_deviation",
)


@dataclass(frozen=True, slots=True)
class WeatherIndexEntry:
    """Latest projected ``weather_index_daily`` row for one weather index.

    Weather indices are *farm-level* first-class indices (one ~9km point
    per farm), so unlike ``IndicesEntry`` (per-block spectral) these are
    keyed only by index_code. ``baseline_deviation`` is the z-score versus
    the farm's day-of-year climatology and is ``None`` until baselines have
    ≥3 samples for that DOY (or for indices like rainfall whose std is ~0 in
    an arid climate) — anomaly predicates then fail closed.
    """

    date: date
    value: Decimal | None = None
    baseline_deviation: Decimal | None = None


# Allowed fields for a weather-risk value-ref (PR-R3). ``score`` is the 0-100
# disease/pest pressure; ``level`` its low|moderate|high banding (a categorical,
# compared with eq/ne). Both None when the block has no ``weather_risk_daily``
# row for that pathogen yet, so a predicate fails closed.
WEATHER_RISK_FIELDS: tuple[str, ...] = (
    "score",
    "level",
)


# Allowed fields for a water-balance value-ref. `balance_mm` is the headline
# (negative = the crop used more than arrived); the rest are the derivation, so
# a tree can branch on WHY rather than only on the answer — high demand, absent
# rain, and unlogged irrigation all produce a negative balance and call for
# different actions.
#
# `irrigation_logged` is here precisely so a tree can refuse to act on a
# deficit it cannot trust. See WaterBalanceValueRef.
WATER_BALANCE_FIELDS: tuple[str, ...] = (
    "balance_mm",
    "etc_mm",
    "et0_mm",
    "kc_used",
    "precip_mm",
    "irrigation_mm",
    "irrigation_logged",
)


@dataclass(frozen=True, slots=True)
class WaterBalanceEntry:
    """Latest ``block_water_balance_daily`` row for one block.

    Block-keyed like ``WeatherRiskEntry`` and for the same reason: the crop
    coefficient and the applied irrigation both vary block to block even
    though the weather driver is the farm centroid.

    Absent for blocks the daily sweep has not written — a block with no
    current crop, or a farm with no ET0 for the day — so ``{source:
    water_balance}`` predicates fail closed.
    """

    date: date
    balance_mm: Decimal | None = None
    etc_mm: Decimal | None = None
    et0_mm: Decimal | None = None
    kc_used: Decimal | None = None
    precip_mm: Decimal | None = None
    irrigation_mm: Decimal | None = None
    irrigation_logged: bool | None = None


@dataclass(frozen=True, slots=True)
class WeatherRiskEntry:
    """Latest ``weather_risk_daily`` row for one pathogen on a block (PR-R3).

    Block-keyed (unlike the farm-level ``WeatherIndexEntry``): risk folds in the
    block's crop + growth stage, so it varies block to block even though the
    weather driver is the farm centroid. ``score`` is the 0-100 accumulation;
    ``level`` its banding. Empty for blocks the daily risk sweep hasn't scored,
    so ``{source: weather_risk}`` predicates fail closed.
    """

    date: date
    score: int | None = None
    level: str | None = None


@dataclass(frozen=True, slots=True)
class IndicesEntry:
    """One row pulled from ``block_index_aggregates`` (latest per index),
    plus precomputed trend features over the recent history (KB P2).

    ``slope`` / ``delta`` are index-units(/day); ``trend_direction`` is
    one of rising/falling/stable. All three are ``None`` when there is too
    little history — the evaluator then fails closed on trend predicates.
    """

    time: datetime
    mean: Decimal | None
    baseline_deviation: Decimal | None
    slope: Decimal | None = None
    delta: Decimal | None = None
    trend_direction: str | None = None


# Allowed keys for a signals value-ref. ``value_kind`` on the underlying
# definition picks which one is non-null; the parser doesn't know the
# kind, so it accepts any of these and the resolver returns ``None`` for
# the wrong one.
# ``value_slope`` / ``value_delta`` / ``value_trend_direction`` (KB P2) are
# precomputed from the numeric observation history of the signal, so a rule
# can say "soil_salinity rising" the same way indices express trends. Only
# meaningful for numeric signals; non-numeric signals leave them None.
SIGNAL_KEYS: tuple[str, ...] = (
    "value_numeric",
    "value_categorical",
    "value_event",
    "value_boolean",
    "value_slope",
    "value_delta",
    "value_trend_direction",
)


@dataclass(frozen=True, slots=True)
class SignalEntry:
    """Latest observation for one signal that applies to the block.

    ``value_*`` are mutually exclusive — exactly one is non-null per
    the signal_definitions row's ``value_kind``. Predicates that read
    the wrong key get ``None`` and short-circuit to no-match.
    """

    time: datetime
    value_numeric: Decimal | None = None
    value_categorical: str | None = None
    value_event: str | None = None
    value_boolean: bool | None = None
    # Trend over the numeric observation history (KB P2); None for
    # non-numeric signals or too-short history.
    value_slope: Decimal | None = None
    value_delta: Decimal | None = None
    value_trend_direction: str | None = None


# Allowed keys for a crop_attribute value-ref. One key today — the recorded
# value itself. Declared as a tuple rather than inlined so a future derivation
# (``days_since`` over a date attribute, which is what would finally let a
# tree ask "current tree age", see the staleness note in
# docs/proposals/crop-custom-attributes.md) can be added without changing the
# ref shape or migrating a single stored condition.
CROP_ATTRIBUTE_KEYS: tuple[str, ...] = ("value",)


# Allowed fields for a grid value-ref (G-4). Each maps 1:1 to a
# ``GridAnomalyEntry`` attribute; ``parse_value_ref`` validates against
# this tuple and the evaluator reads via ``getattr``.
GRID_FIELDS: tuple[str, ...] = (
    "worst_z",  # std-devs the worst flagged cell sits below the field mean
    "flagged_count",  # how many cells crossed the threshold
    "worst_row",  # grid row of the worst cell
    "worst_col",  # grid col of the worst cell
    "severity",  # "warning" | "critical"
)


@dataclass(frozen=True, slots=True)
class GridAnomalyEntry:
    """Latest sub-block grid spatial-anomaly verdict for one index (G-4).

    Present in ``ConditionContext.grid`` only when the latest scene for
    that (block, index) crossed the detection threshold — a tree
    predicate against an index with no current anomaly resolves to
    ``None`` and fails closed, matching every other source. Lets a
    decision tree branch on *where/how-bad* a spatial anomaly is, e.g.
    ``{source: grid, index_code: ndvi, field: flagged_count} >= 5``.
    """

    worst_z: Decimal | None = None
    flagged_count: int | None = None
    worst_row: int | None = None
    worst_col: int | None = None
    severity: str | None = None


# Allowed scope keys for a weather value-ref. Keep in lock-step with
# ``WeatherSnapshot`` field names below — ``parse_value_ref`` validates
# against this tuple.
WEATHER_SCOPES: tuple[str, ...] = (
    "latest_observation",
    "forecast_24h",
    "forecast_72h",
    "derived_today",
    "derived_yesterday",
)


@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    """All weather inputs needed for one block evaluation.

    Each scope is a flat ``{field: Decimal | None}`` dict so the
    value-ref resolver is a two-level lookup. Missing scope or missing
    field both resolve to ``None`` (evaluator branches to ``on_miss``).

    ``latest_observation`` carries the latest hourly observation row's
    columns: ``air_temp_c``, ``humidity_pct``, ``precipitation_mm``,
    ``wind_speed_m_s``, ``et0_mm``, etc.

    Forecast windows pre-aggregate over the next 24h / 72h:
      * ``precipitation_mm_total`` — sum
      * ``precipitation_probability_pct_max`` — max
      * ``air_temp_c_max`` / ``air_temp_c_min`` — max / min
      * ``et0_mm_total`` — sum

    ``derived_today`` / ``derived_yesterday`` are the per-day rows from
    ``weather_derived_daily`` keyed on (farm_id, date) — fields like
    ``precip_mm_7d``, ``gdd_cumulative_base10_season``, ``temp_max_c``.
    """

    latest_observation: dict[str, Decimal | None] | None = None
    forecast_24h: dict[str, Decimal | None] | None = None
    forecast_72h: dict[str, Decimal | None] | None = None
    derived_today: dict[str, Decimal | None] | None = None
    derived_yesterday: dict[str, Decimal | None] | None = None


@dataclass(frozen=True, slots=True)
class ConditionContext:
    """Per-block snapshot the evaluator reads.

    Treat as additive: new fields mean "more rules can be expressed".
    Removing a field is a breaking change for any persisted rule that
    references it.
    """

    block_id: str
    block_attributes: dict[str, Any] = field(default_factory=dict)
    indices: dict[str, IndicesEntry] = field(default_factory=dict)
    weather: WeatherSnapshot | None = None
    # Farm-level first-class weather indices keyed by index_code (PR-W7);
    # each carries the latest value + its z-score against the DOY
    # climatology. Empty for farms with no projected `weather_index_daily`
    # rows, so `{source: weather_index}` predicates fail closed.
    weather_indices: dict[str, WeatherIndexEntry] = field(default_factory=dict)
    # Per-block weather-driven disease/pest risk scores keyed by risk_code
    # (PR-R3); each carries the latest 0-100 score + low|moderate|high level.
    # Empty for blocks the daily risk sweep hasn't scored, so
    # `{source: weather_risk}` predicates fail closed.
    weather_risks: dict[str, WeatherRiskEntry] = field(default_factory=dict)
    # None (not an empty entry) when the sweep has written nothing for this
    # block, so a predicate fails closed rather than reading zeros as facts.
    water_balance: WaterBalanceEntry | None = None
    signals: dict[str, SignalEntry] = field(default_factory=dict)
    # Sub-block grid spatial-anomaly verdicts keyed by index_code (G-4).
    # Populated by the recommendations driver only when the block has an
    # active grid with a current anomaly; empty otherwise.
    grid: dict[str, GridAnomalyEntry] = field(default_factory=dict)
    # Platform-curated crop attributes recorded on the block's *current* crop
    # assignment, keyed by definition code and already typed by the
    # definition's value_type (Decimal / date / str / list[str]). Empty when
    # the block has no current assignment or the crop defines no attributes,
    # so `{source: crop_attribute}` predicates fail closed like every other
    # source. A plain dict rather than an entry dataclass: unlike indices or
    # signals there is exactly one value per code and no derived companions.
    crop_attributes: dict[str, Any] = field(default_factory=dict)
    # Decision-tree parameter values (PR-B): {name: value} resolved
    # from the tree's `parameters:` defaults, layered with tenant
    # overrides in PR-C. The alerts engine leaves this empty.
    # `{source: params, name: x}` resolves via this dict; missing keys
    # return None (permissive).
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_block_signals(
        cls,
        *,
        block_id: str,
        latest_index_aggregates: dict[str, dict[str, Any]],
        block_attributes: dict[str, Any] | None = None,
        weather: WeatherSnapshot | None = None,
        weather_indices: dict[str, WeatherIndexEntry] | None = None,
        weather_risks: dict[str, WeatherRiskEntry] | None = None,
        water_balance: WaterBalanceEntry | None = None,
        signals: dict[str, SignalEntry] | None = None,
        grid: dict[str, GridAnomalyEntry] | None = None,
        crop_attributes: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> ConditionContext:
        """Build a context from the ``BlockSignals`` shape the alerts
        engine already loads. ``weather`` and ``signals`` are optional —
        services that don't load them pass ``None`` / ``{}`` and the
        evaluator returns ``False`` for any predicate that references
        them (permissive on missing data).
        """
        indices: dict[str, IndicesEntry] = {}
        for code, row in latest_index_aggregates.items():
            indices[code] = IndicesEntry(
                # ``time`` is always present on an aggregate row (required on
                # IndicesEntry); index access keeps the type as Any rather than
                # Optional, so it satisfies the datetime field.
                time=row["time"],
                mean=_to_decimal(row.get("mean")),
                baseline_deviation=_to_decimal(row.get("baseline_deviation")),
                # Trend features (KB P2) — the service merges these into the
                # row from the recent aggregate history; absent → None.
                slope=_to_decimal(row.get("slope")),
                delta=_to_decimal(row.get("delta")),
                trend_direction=row.get("trend_direction"),
            )
        return cls(
            block_id=block_id,
            block_attributes=dict(block_attributes or {}),
            indices=indices,
            weather=weather,
            weather_indices=weather_indices or {},
            weather_risks=weather_risks or {},
            water_balance=water_balance,
            signals=signals or {},
            grid=grid or {},
            crop_attributes=dict(crop_attributes or {}),
            params=dict(params or {}),
        )


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
