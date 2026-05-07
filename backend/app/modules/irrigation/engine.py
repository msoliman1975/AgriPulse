"""Pure-function irrigation-recommendation engine.

The Beat task and the on-demand `generate_for_block` service path both
funnel through these helpers; the DB layer never sees the merged
inputs. Two responsibilities:

  1. **Crop coefficient (Kc) lookup** — given a stage code, find the
     matching ``Kc`` from the crop's (or variety override's)
     ``phenology_stages`` JSONB. Falls back to a built-in default per
     stage so the engine still works for crops without a populated
     phenology curve. This is intentionally permissive: PR-2 made the
     phenology JSONB optional.
  2. **Water-balance recommendation** —
     ``recommended_mm = max(0, kc * et0 - recent_precip - safety_buffer)``.
     The safety buffer accounts for application efficiency
     (drip ≈ 90%, surface ≈ 60%); we keep the API generic so the
     caller passes the appropriate factor.

Inputs are explicit so unit tests can exercise the math without
loading anything from the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# --- Kc fallback table (FAO-56 textbook approximations) -------------------
#
# Used when the crop's phenology_stages JSONB doesn't supply a Kc for the
# current growth_stage. Values are conservative defaults; once a crop's
# `phenology_stages` carry per-stage Kc values, those win.
_DEFAULT_KC_BY_STAGE: dict[str, Decimal] = {
    "germination": Decimal("0.30"),
    "vegetative": Decimal("0.70"),
    "flowering": Decimal("1.10"),
    "fruit_set": Decimal("1.10"),
    "fruit_development": Decimal("1.05"),
    "maturity": Decimal("0.85"),
    "ripening": Decimal("0.75"),
    "senescence": Decimal("0.60"),
    # Generic fallback bucket — used when stage isn't known.
    "default": Decimal("0.85"),
}


@dataclass(frozen=True, slots=True)
class IrrigationInputs:
    """Snapshot of everything the engine needs to produce one
    recommendation. Loaded by the service from `weather_derived_daily`,
    `block_crops`, and the public crop catalog."""

    et0_mm_today: Decimal
    """ET₀ for the target day. From `weather_derived_daily.et0_mm_daily`."""

    recent_precip_mm: Decimal
    """Sum of precipitation in a configured lookback (typically 1-3
    days). Subtracts from ET₀ so we don't water on top of fresh rain.
    Pass zero if unknown — the engine treats absence as 'no rain'."""

    growth_stage: str | None
    """Code from `block_crops.growth_stage` if any. Drives Kc lookup."""

    phenology_stages: dict[str, Any] | None
    """Resolved JSONB from `crops.phenology_stages` merged with
    `crop_varieties.phenology_stages_override` (PR-2's
    `crop_thresholds.resolve_phenology_stages`). Either the dict from
    the catalog or None for unknown crops."""

    application_efficiency: Decimal
    """0..1 scalar — drip ≈ 0.90, surface ≈ 0.60. The engine divides
    the net water requirement by this so the *delivered* volume
    accounts for losses."""


@dataclass(frozen=True, slots=True)
class Recommendation:
    """Engine output ready to write to ``irrigation_schedules``."""

    recommended_mm: Decimal
    kc_used: Decimal
    et0_mm_used: Decimal
    recent_precip_mm: Decimal
    growth_stage_context: str


def lookup_kc(*, growth_stage: str | None, phenology_stages: dict[str, Any] | None) -> Decimal:
    """Resolve a Kc value for the current stage.

    Priority:
      1. Per-stage entry in the crop's (or variety's) phenology_stages
         JSONB if it has a numeric ``kc`` field.
      2. Built-in default in ``_DEFAULT_KC_BY_STAGE``.
      3. ``_DEFAULT_KC_BY_STAGE['default']``.
    """
    catalog_kc = _phenology_kc(growth_stage, phenology_stages)
    if catalog_kc is not None:
        return catalog_kc
    if growth_stage and growth_stage in _DEFAULT_KC_BY_STAGE:
        return _DEFAULT_KC_BY_STAGE[growth_stage]
    return _DEFAULT_KC_BY_STAGE["default"]


def _phenology_kc(stage: str | None, stages_doc: dict[str, Any] | None) -> Decimal | None:
    """Pull the Kc field from the crop's phenology_stages JSONB if
    present. The shape is intentionally lenient — older catalogs may
    have ``stages`` as a list, newer ones as a dict keyed by stage code.
    Either layout works.
    """
    if stage is None or stages_doc is None:
        return None
    raw_stages = stages_doc.get("stages") if isinstance(stages_doc, dict) else None
    candidates: list[tuple[bool, dict[str, Any]]] = []
    # `pre_keyed` = True when the entry is reached via dict-key match,
    # so the inner loop doesn't re-check `code` / `name`.
    if isinstance(raw_stages, list):
        candidates = [(False, s) for s in raw_stages if isinstance(s, dict)]
    elif (
        isinstance(raw_stages, dict) and stage in raw_stages and isinstance(raw_stages[stage], dict)
    ):
        candidates = [(True, raw_stages[stage])]
    for pre_keyed, entry in candidates:
        if not pre_keyed:
            # Two ways to identify the stage: ``code`` or ``name``.
            code = entry.get("code") or entry.get("name")
            if code != stage:
                continue
        kc_raw = entry.get("kc") or entry.get("Kc")
        if kc_raw is None:
            continue
        try:
            return Decimal(str(kc_raw))
        except (ValueError, ArithmeticError):
            return None
    return None


def compute_recommendation(inputs: IrrigationInputs) -> Recommendation:
    """Run the water-balance formula and produce a recommendation.

    ``recommended_mm = max(0, (kc * et0 - recent_precip)) /
    application_efficiency``

    Quantised to two decimals; never negative (a negative deficit
    means the rain alone covered the crop's demand).
    """
    if inputs.application_efficiency <= 0:
        raise ValueError("application_efficiency must be > 0")

    kc = lookup_kc(
        growth_stage=inputs.growth_stage,
        phenology_stages=inputs.phenology_stages,
    )
    crop_demand = (kc * inputs.et0_mm_today).quantize(Decimal("0.01"))
    deficit = crop_demand - inputs.recent_precip_mm
    if deficit <= 0:
        recommended = Decimal("0.00")
    else:
        recommended = (deficit / inputs.application_efficiency).quantize(Decimal("0.01"))

    return Recommendation(
        recommended_mm=recommended,
        kc_used=kc,
        et0_mm_used=inputs.et0_mm_today.quantize(Decimal("0.01")),
        recent_precip_mm=inputs.recent_precip_mm.quantize(Decimal("0.01")),
        growth_stage_context=inputs.growth_stage or "unknown",
    )
