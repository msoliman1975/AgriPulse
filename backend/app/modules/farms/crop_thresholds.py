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
        return _inherit_kc(strain_override, variety_override, crop_stages)
    if variety_override is not None:
        return _inherit_kc(variety_override, crop_stages)
    return crop_stages


def _stage_entries(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The stage dicts of a phenology document, list or code-keyed dict."""
    raw = doc.get("stages") if isinstance(doc, dict) else None
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    if isinstance(raw, dict):
        return [dict(v, code=v.get("code") or k) for k, v in raw.items() if isinstance(v, dict)]
    return []


def _inherit_kc(winner: dict[str, Any], *ancestors: dict[str, Any] | None) -> dict[str, Any]:
    """Fill each stage's missing ``kc`` from the nearest ancestor stage with the same code.

    An override replaces the stage list wholesale, so a variety calendar that
    says nothing about Kc used to drop the crop's per-stage values and send the
    irrigation engine to its built-in defaults (decision D19: Medjool lost the
    FAO date palm Kc of migration 0064). A stage's own ``kc`` always wins; the
    nearest level that has the same stage code fills a gap. Stages no ancestor
    knows keep no Kc. The input documents are not mutated.
    """
    raw = winner.get("stages") if isinstance(winner, dict) else None
    if not isinstance(raw, list | dict):
        return winner
    lookups = [
        {(e.get("code") or e.get("name")): e.get("kc", e.get("Kc")) for e in _stage_entries(a)}
        for a in ancestors
    ]

    def fill(entry: dict[str, Any], code: str | None) -> dict[str, Any]:
        if entry.get("kc") is not None or entry.get("Kc") is not None or code is None:
            return entry
        for lookup in lookups:
            kc = lookup.get(code)
            if kc is not None:
                return {**entry, "kc": kc}
        return entry

    if isinstance(raw, list):
        stages: Any = [
            fill(e, e.get("code") or e.get("name")) if isinstance(e, dict) else e for e in raw
        ]
        changed = any(a is not b for a, b in zip(stages, raw, strict=True))
    else:
        stages = {
            k: fill(v, v.get("code") or k) if isinstance(v, dict) else v for k, v in raw.items()
        }
        changed = any(stages[k] is not raw[k] for k in raw)
    # Nothing filled: hand back the caller's own document, as before.
    return {**winner, "stages": stages} if changed else winner


def resolve_size_classes(
    *,
    crop_classes: dict[str, Any] | None,
    variety_override: dict[str, Any] | None,
    strain_override: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Deepest non-NULL canopy-size-class override wins (strain → variety → crop).

    Mirrors :func:`resolve_phenology_stages`: the ``{"classes": [...]}``
    payload is replaced wholesale rather than merged. Returns ``None`` when
    no level defines size classes.
    """
    if strain_override is not None:
        return strain_override
    if variety_override is not None:
        return variety_override
    return crop_classes
