"""Pre-loaded data the evaluator reads from.

The service layer (alerts engine driver, recommendations evaluator)
loads a ``ConditionContext`` once per block per evaluation pass and
hands it to ``evaluate``. Adding a new source means adding a field
here and teaching the relevant value-ref resolver to read it; the
evaluator core stays untouched.

Currently wired sources: ``indices`` (NDVI / EVI / etc. aggregates),
``block`` (crop_category and other block attributes), and ``weather``
(latest observation, near-term forecast windows, derived daily). The
``signals`` source is still unbuilt — rules that reference it return
``(False, {})`` per the permissive-on-missing-data contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class IndicesEntry:
    """One row pulled from ``block_index_aggregates`` (latest per index)."""

    time: datetime
    mean: Decimal | None
    baseline_deviation: Decimal | None


# Allowed keys for a signals value-ref. ``value_kind`` on the underlying
# definition picks which one is non-null; the parser doesn't know the
# kind, so it accepts any of these and the resolver returns ``None`` for
# the wrong one.
SIGNAL_KEYS: tuple[str, ...] = (
    "value_numeric",
    "value_categorical",
    "value_event",
    "value_boolean",
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
    crop_category: str | None = None
    block_attributes: dict[str, Any] = field(default_factory=dict)
    indices: dict[str, IndicesEntry] = field(default_factory=dict)
    weather: WeatherSnapshot | None = None
    signals: dict[str, SignalEntry] = field(default_factory=dict)
    # Sub-block grid spatial-anomaly verdicts keyed by index_code (G-4).
    # Populated by the recommendations driver only when the block has an
    # active grid with a current anomaly; empty otherwise.
    grid: dict[str, GridAnomalyEntry] = field(default_factory=dict)
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
        crop_category: str | None,
        latest_index_aggregates: dict[str, dict[str, Any]],
        block_attributes: dict[str, Any] | None = None,
        weather: WeatherSnapshot | None = None,
        signals: dict[str, SignalEntry] | None = None,
        grid: dict[str, GridAnomalyEntry] | None = None,
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
                time=row.get("time"),  # type: ignore[arg-type]
                mean=_to_decimal(row.get("mean")),
                baseline_deviation=_to_decimal(row.get("baseline_deviation")),
            )
        return cls(
            block_id=block_id,
            crop_category=crop_category,
            block_attributes=dict(block_attributes or {}),
            indices=indices,
            weather=weather,
            signals=signals or {},
            grid=grid or {},
            params=dict(params or {}),
        )


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
