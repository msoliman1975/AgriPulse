"""One reading of a finding's evidence and description, shared by every
surface that shows it.

The user-visible complaint this answers: an alert email said only
``Warning · My new tree — 045, Mango Republic`` and, in the body, the
leaf's own sentence. It never said what the tree is for, and never said
what was actually measured. The Action Center had the same gap. Two
screens and three channels each deciding for themselves what a finding
"says" is how they drifted, so the decision lives here once and they all
call it.

A finding's description has three parts, in the order a reader needs
them:

1. **Verdict** — the sentence the tree's leaf wrote (``diagnosis_en`` on
   an alert, ``text_en`` on a recommendation). What this block is.
2. **Why this tree ran** — ``decision_trees.description_en``. The
   author's one paragraph on what the tree looks for. Written at
   authoring time and, until now, shown nowhere at all.
3. **What we measured** — the values the walk actually resolved, from
   ``signal_snapshot`` / ``resolved_values``. This is the part that turns
   "Warning" into something a person can check.

Nothing here invents a number. A key whose value is ``null`` renders as
"no data" rather than being dropped: a tree that fired *because* an index
was missing is the exact case where a silent omission misleads.
"""

from __future__ import annotations

from typing import Any

DEFAULT_LOCALE = "en"

# Index codes are shown upper-case (NDVI, not Ndvi). Anything not listed
# falls back to upper-casing the code, so a newly seeded index reads
# correctly without a change here.
_STAT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "mean": "{code} mean",
        "min": "{code} minimum",
        "max": "{code} maximum",
        "median": "{code} median",
        "stddev": "{code} spread",
        "baseline_deviation": "{code} vs its own baseline",
        "p10": "{code} 10th percentile",
        "p90": "{code} 90th percentile",
    },
    "ar": {
        "mean": "متوسط {code}",
        "min": "أدنى {code}",
        "max": "أعلى {code}",
        "median": "وسيط {code}",
        "stddev": "تشتت {code}",
        "baseline_deviation": "انحراف {code} عن خط الأساس",
        "p10": "{code} المئين 10",
        "p90": "{code} المئين 90",
    },
}

_BLOCK_FIELD_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "growth_stage": "Growth stage",
        "soil_texture": "Soil texture",
        "crop": "Crop",
        "area_ha": "Area (ha)",
        "planting_date": "Planting date",
    },
    "ar": {
        "growth_stage": "مرحلة النمو",
        "soil_texture": "قوام التربة",
        "crop": "المحصول",
        "area_ha": "المساحة (هكتار)",
        "planting_date": "تاريخ الزراعة",
    },
}

_WEATHER_LABELS: dict[str, dict[str, str]] = {
    "en": {"mean": "{code} mean", "sum": "{code} total", "max": "{code} maximum"},
    "ar": {"mean": "متوسط {code}", "sum": "إجمالي {code}", "max": "أعلى {code}"},
}

# Keys with no dotted family. `crop_path` is the only one the engine
# resolves today; it appears in most recommendation snapshots and read
# as the bare word "crop_path" next to properly labelled rows.
_BARE_LABELS: dict[str, dict[str, str]] = {
    "en": {"crop_path": "Crop", "growth_stage": "Growth stage"},
    "ar": {"crop_path": "المحصول", "growth_stage": "مرحلة النمو"},
}

_NO_DATA = {"en": "no data", "ar": "لا توجد بيانات"}
_TRUE = {"en": "yes", "ar": "نعم"}
_FALSE = {"en": "no", "ar": "لا"}


def _table(source: dict[str, dict[str, str]], locale: str) -> dict[str, str]:
    return source.get(locale) or source[DEFAULT_LOCALE]


def _humanise(token: str) -> str:
    return token.replace("_", " ").strip().capitalize()


def evidence_label(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Turn a resolved-value key into words.

    Keys are the dotted paths the condition engine resolves:
    ``indices.ndvi.mean``, ``weather.gdd.sum``, ``block.growth_stage``,
    ``crop_attribute.tree_size_class.value``, ``params.dry_z``.
    An unrecognised shape degrades to the key itself rather than to
    blank — a label nobody wrote is better than a row nobody can
    identify.
    """
    parts = key.split(".")
    family = parts[0] if parts else key

    if family in {"indices", "weather"} and len(parts) >= 3:
        code = parts[1].upper()
        table = _STAT_LABELS if family == "indices" else _WEATHER_LABELS
        pattern = _table(table, locale).get(parts[2])
        return pattern.format(code=code) if pattern else f"{code} {_humanise(parts[2])}"

    if len(parts) >= 2:
        # `block.<field>` has a translated label where one was written;
        # `crop_attribute.<name>.value` and `params.<name>` are named by
        # whoever authored them, so the name itself is the label — the
        # trailing `.value` on a crop attribute is storage shape, not
        # something a reader should be shown.
        if family == "block":
            return _table(_BLOCK_FIELD_LABELS, locale).get(parts[1]) or _humanise(parts[1])
        if family in {"crop_attribute", "params"}:
            return _humanise(parts[1])
        return key

    # A key with no family at all. `crop_path` is the only one the engine
    # resolves today, and it appeared in nearly every recommendation
    # snapshot as the bare word beside properly labelled rows.
    return _table(_BARE_LABELS, locale).get(key) or key


def evidence_value(value: Any, locale: str = DEFAULT_LOCALE) -> str:
    """Format one resolved value for reading.

    ``None`` becomes "no data" and is never dropped. A tree can fire
    *because* a value is missing — that is exactly what happened to the
    Mango Republic blocks, whose NDVI mean was null — and hiding the row
    would leave the reader with a Warning and no stated reason.
    """
    if value is None:
        return _table_str(_NO_DATA, locale)
    if isinstance(value, bool):
        return _table_str(_TRUE if value else _FALSE, locale)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Three decimals: index values live in [-1, 1] and two is not
        # enough to tell 0.205 from 0.214, which can be two verdicts.
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, list):
        return ", ".join(evidence_value(item, locale) for item in value)
    return str(value)


def _table_str(source: dict[str, str], locale: str) -> str:
    return source.get(locale) or source[DEFAULT_LOCALE]


def evidence_rows(
    snapshot: dict[str, Any] | None,
    *,
    locale: str = DEFAULT_LOCALE,
    include_params: bool = False,
    limit: int = 8,
) -> list[tuple[str, str]]:
    """``[(label, value)]`` for the values a finding was decided on.

    ``params.*`` keys are left out by default. They are the tree's own
    thresholds — configuration, not measurement — and mixing them into
    "what we measured" invites a reader to think the platform observed a
    number it only ever read from a settings row.

    Ordering is by key so two blocks with the same finding describe it in
    the same order. ``limit`` caps an email's fact table; the caller is
    told how many were cut by comparing against the input length.
    """
    if not snapshot:
        return []
    keys = sorted(
        k
        for k, v in snapshot.items()
        if (include_params or not k.startswith("params."))
        # A nested object has no one-line reading. Printing `{'a': 1}` in a
        # fact table tells the reader less than leaving the row out, and
        # tells them it in a shape that looks like a bug.
        and not isinstance(v, dict)
    )
    return [(evidence_label(k, locale), evidence_value(snapshot[k], locale)) for k in keys[:limit]]


def evidence_text(
    snapshot: dict[str, Any] | None,
    *,
    locale: str = DEFAULT_LOCALE,
    separator: str = " · ",
    limit: int = 8,
) -> str:
    """One-line form of :func:`evidence_rows`, for plain-text email,
    push bodies and anywhere a table will not fit."""
    rows = evidence_rows(snapshot, locale=locale, limit=limit)
    return separator.join(f"{label}: {value}" for label, value in rows)
