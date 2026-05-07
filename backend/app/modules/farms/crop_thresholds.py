"""Threshold + phenology resolution for the agronomy engine.

The catalog stores defaults at two levels:

  * ``crops.default_thresholds`` — platform default for every variety
    of a crop (NDVI deviation cutoffs, frost cutoff, irrigation
    deficit triggers, chill-hour requirement, etc.).
  * ``crop_varieties.default_thresholds`` — per-variety override.
  * ``crop_varieties.phenology_stages_override`` — per-variety
    phenology if it differs from the crop default.

Future PRs (alerts, recommendations, irrigation scheduling) consult
these thresholds when evaluating rules. The functions here are pure —
no DB, no I/O — so callers can unit-test them quickly and engines can
batch-resolve in memory once the catalog rows are loaded.

Resolution rules:

  * ``default_thresholds``: shallow merge — variety wins per key. If
    both are NULL the result is ``{}``. The shape is opaque JSON; we
    do not validate keys here because rules engines will define them.
  * ``phenology_stages``: variety override replaces wholesale. If the
    variety override is NULL, the crop's stages flow through. The
    array of ``{stage, start_gdd, end_gdd, ...}`` rows is too
    irregular to merge keywise.
"""

from __future__ import annotations

from typing import Any


def resolve_thresholds(
    *,
    crop_thresholds: dict[str, Any] | None,
    variety_thresholds: dict[str, Any] | None,
) -> dict[str, Any]:
    """Shallow-merge crop defaults with variety overrides; variety wins.

    >>> resolve_thresholds(
    ...     crop_thresholds={"ndvi_deviation_warning_pct": -10, "frost_threshold_c": 2},
    ...     variety_thresholds={"ndvi_deviation_warning_pct": -15},
    ... )
    {'ndvi_deviation_warning_pct': -15, 'frost_threshold_c': 2}

    Both NULL collapses to ``{}`` so callers don't have to special-case it.
    """
    merged: dict[str, Any] = {}
    if crop_thresholds:
        merged.update(crop_thresholds)
    if variety_thresholds:
        merged.update(variety_thresholds)
    return merged


def resolve_phenology_stages(
    *,
    crop_stages: dict[str, Any] | None,
    variety_override: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Variety override takes precedence; otherwise inherit the crop's.

    Returns ``None`` if neither side has stages — the consumer must
    decide whether to fall back to a built-in default or skip
    phenology-aware logic for that block.
    """
    if variety_override is not None:
        return variety_override
    return crop_stages
