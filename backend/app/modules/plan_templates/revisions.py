"""Manual snapshots and diffs by activity code (Agri Operation PR 4).

A snapshot is ``{code: {field: value}}`` for a manual's activities. Two are
kept: the manual at its last publish (``plan_templates.published_snapshot``,
for the Publish step, H6) and the manual as a saved plan last applied it
(``plan_allocations.manual_snapshot``, for "manual updated", B4). Pure.
"""

from __future__ import annotations

from typing import Any

# Keep in step with the backfill SQL in public migration 0107.
SNAPSHOT_FIELDS = (
    "activity_type",
    "title",
    "title_ar",
    "anchor",
    "stage_code",
    "milestone_code",
    "offset_days",
    "duration_days",
    "product_name",
    "dosage",
    "notes",
    "product_name_ar",
    "dosage_ar",
    "notes_ar",
    "evidence_tier",
    "source_tree_code",
)


def snapshot_of(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Snapshot a full tree (as ``get_full_tree`` returns it)."""
    milestone_codes = {m["id"]: m["code"] for m in tree.get("milestones", [])}
    out: dict[str, dict[str, Any]] = {}
    for a in tree.get("activities", []):
        row = {f: a.get(f) for f in SNAPSHOT_FIELDS if f != "milestone_code"}
        row["milestone_code"] = milestone_codes.get(a.get("milestone_id"))
        out[str(a["code"])] = row
    return out


def _label(row: dict[str, Any] | None, code: str) -> dict[str, Any]:
    row = row or {}
    return {
        "code": code,
        "title": row.get("title"),
        "title_ar": row.get("title_ar"),
        "activity_type": row.get("activity_type"),
    }


def diff_snapshots(
    old: dict[str, dict[str, Any]] | None, new: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """What changed from ``old`` to ``new``, by activity code.

    ``old`` None means there is nothing to compare against (never published,
    or a saved plan applied before snapshots existed): every list is empty and
    ``comparable`` is False.
    """
    if old is None:
        return {"comparable": False, "added": [], "removed": [], "changed": []}
    added = [_label(new[c], c) for c in sorted(new.keys() - old.keys())]
    removed = [_label(old[c], c) for c in sorted(old.keys() - new.keys())]
    changed = []
    for code in sorted(old.keys() & new.keys()):
        fields = [f for f in SNAPSHOT_FIELDS if old[code].get(f) != new[code].get(f)]
        if fields:
            changed.append({**_label(new[code], code), "fields": fields})
    return {"comparable": True, "added": added, "removed": removed, "changed": changed}


__all__ = ["SNAPSHOT_FIELDS", "diff_snapshots", "snapshot_of"]
