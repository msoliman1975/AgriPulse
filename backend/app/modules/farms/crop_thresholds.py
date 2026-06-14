"""Threshold + phenology resolution for the agronomy engine.

The catalog stores defaults at three levels (Crop → Variety → Strain):

  * ``crops.default_thresholds`` — platform default for every variety
    of a crop (NDVI deviation cutoffs, frost cutoff, irrigation
    deficit triggers, chill-hour requirement, etc.).
  * ``crop_varieties.default_thresholds`` — per-variety override.
  * ``crop_variety_strains.default_thresholds`` — per-strain override
    (deepest taxonomy level).
  * ``crop_varieties.phenology_stages_override`` /
    ``crop_variety_strains.phenology_stages_override`` — per-variety /
    per-strain phenology if it differs from the level above.

Future PRs (alerts, recommendations, irrigation scheduling) consult
these thresholds when evaluating rules. The functions here are pure —
no DB, no I/O — so callers can unit-test them quickly and engines can
batch-resolve in memory once the catalog rows are loaded.

Resolution rules:

  * ``default_thresholds``: shallow merge crop → variety → strain, the
    deepest specified level winning per key. If all are NULL the result
    is ``{}``. The shape is opaque JSON; we do not validate keys here
    because rules engines will define them.
  * ``phenology_stages``: the deepest non-NULL override replaces
    wholesale (strain beats variety beats crop). The array of
    ``{stage, start_gdd, end_gdd, ...}`` rows is too irregular to merge
    keywise.
"""

from __future__ import annotations

from typing import Any


def resolve_thresholds(
    *,
    crop_thresholds: dict[str, Any] | None,
    variety_thresholds: dict[str, Any] | None,
    strain_thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shallow-merge crop → variety → strain defaults; deepest level wins.

    >>> resolve_thresholds(
    ...     crop_thresholds={"ndvi_deviation_warning_pct": -10, "frost_threshold_c": 2},
    ...     variety_thresholds={"ndvi_deviation_warning_pct": -15},
    ...     strain_thresholds={"frost_threshold_c": 0},
    ... )
    {'ndvi_deviation_warning_pct': -15, 'frost_threshold_c': 0}

    All NULL collapses to ``{}`` so callers don't have to special-case it.
    """
    merged: dict[str, Any] = {}
    if crop_thresholds:
        merged.update(crop_thresholds)
    if variety_thresholds:
        merged.update(variety_thresholds)
    if strain_thresholds:
        merged.update(strain_thresholds)
    return merged


def resolve_phenology_stages(
    *,
    crop_stages: dict[str, Any] | None,
    variety_override: dict[str, Any] | None,
    strain_override: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Deepest non-NULL override wins (strain → variety → crop).

    Returns ``None`` if no level has stages — the consumer must decide
    whether to fall back to a built-in default or skip phenology-aware
    logic for that block.
    """
    if strain_override is not None:
        return strain_override
    if variety_override is not None:
        return variety_override
    return crop_stages
