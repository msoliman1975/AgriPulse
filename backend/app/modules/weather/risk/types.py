"""Pure value types for the weather-driven disease/pest risk models (PR-R1).

Self-contained (stdlib only) so the model library, the daily risk task
(PR-R2) and the unit tests share one vocabulary without importing any DB /
ORM code. See ``docs/proposals/weather-indices-first-class.md`` §2.3/§3.

The shapes mirror the ``weather_risk_daily`` table: a model turns a trailing
window of :class:`RiskWeatherDay` plus the block's :class:`RiskBlockContext`
into a :class:`RiskScore` (``score`` 0-100, ``level`` banding, ``inputs`` the
"why" persisted to the jsonb column).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal
from enum import Enum


class RiskLevel(str, Enum):
    """Banding of a 0-100 risk score. Ordered low < moderate < high."""

    low = "low"
    moderate = "moderate"
    high = "high"


@dataclass(frozen=True, slots=True)
class RiskWeatherDay:
    """One farm-local day of the weather signals the risk models read.

    Sourced (in PR-R2) from ``weather_derived_daily`` (temp/precip) plus the
    radiation/wind day aggregation (humidity). Every field is optional: a gap
    day simply contributes nothing to a model's accumulation rather than
    aborting it.
    """

    date: date_type
    temp_min_c: Decimal | None = None
    temp_max_c: Decimal | None = None
    temp_mean_c: Decimal | None = None
    humidity_mean_pct: Decimal | None = None
    precip_mm: Decimal | None = None
    # Hours at/above 90% RH (NHRH90). Optional and defaulted like everything
    # else here, which matters more for this field than the rest: it only
    # exists for days projected after the leaf-wetness work landed, so every
    # model reading it must keep its pre-existing daily-mean-RH path as the
    # fallback rather than treating None as "dry".
    leaf_wetness_hours: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RiskBlockContext:
    """The per-block crop facts a model folds in (read from ``block_crops``).

    ``crop_path`` selects which models apply (prefix match, e.g. ``mango`` ->
    ``mango.keitt.large``). ``growth_stage`` / ``canopy_size_class`` modulate
    susceptibility; both optional so risk still computes (weather-only) before
    the phenology spine has advanced a block — the graceful-degradation
    contract from the proposal.
    """

    crop_path: str
    growth_stage: str | None = None
    canopy_size_class: str | None = None


@dataclass(frozen=True, slots=True)
class RiskScore:
    """One ``weather_risk_daily`` row, pre-persistence.

    ``score`` is an integer 0-100; ``level`` its banding; ``inputs`` the
    accumulation breakdown that produced it (Decimals serialised as strings,
    matching the ``value_aux`` Decimal->string JSON convention) so the map
    popup can show the contributing conditions.
    """

    risk_code: str
    score: int
    level: RiskLevel
    inputs: dict[str, str] = field(default_factory=dict)


__all__ = ["RiskLevel", "RiskWeatherDay", "RiskBlockContext", "RiskScore"]
