"""D26: operation manual activities are saved with Arabic beside English.

Manuals are platform content (``public.plan_templates``) saved as one
document, so what is new is decided against the stored tree: each activity's
title, notes, product and dosage, matched by activity code. An activity
without a code is new (the code is assigned on save). The manual's own name
and its milestone names are not checked yet (a follow-up); activities are the
text a grower reads on the Plan board.

Only English text this save adds or changes, or Arabic it clears, has to
carry Arabic. Seeded manuals that never had Arabic product names still
resave untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.arabic_required import Pair, missing_arabic

ACTIVITY_PAIRS: tuple[Pair, ...] = (
    ("title", "title_ar"),
    ("notes", "notes_ar"),
    ("product_name", "product_name_ar"),
    ("dosage", "dosage_ar"),
)


def _by_code(rows: Any) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows or []:
        code = row.get("code") if isinstance(row, Mapping) else None
        if code:
            out[str(code)] = row
    return out


def missing_manual_arabic(
    payload: Mapping[str, Any], previous: Mapping[str, Any] | None
) -> list[Pair]:
    """The Arabic fields this manual save leaves empty, named by position.

    ``payload`` is the write request as a dict; ``previous`` is the stored
    full tree (``get_full_tree``), or ``None`` for a new manual.
    """
    missing: list[Pair] = []
    before_activities = _by_code(previous.get("activities")) if previous is not None else {}
    for idx, a in enumerate(payload.get("activities") or [], start=1):
        code = a.get("code")
        before = before_activities.get(str(code)) if code and previous is not None else None
        missing += missing_arabic(a, ACTIVITY_PAIRS, before=before, prefix=f"activities[{idx}].")
    return missing
