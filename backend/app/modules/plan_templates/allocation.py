"""Pure resolver for a saved Agri Operation plan (allocation) on one block.

Builds on :func:`app.modules.plan_templates.apply.resolve_schedule` (the
manual's anchors: start, milestone, stage) and layers the farm's own changes:

1. drop manual activities whose code is in ``excluded_codes`` (D1);
2. apply ``activity_edits`` to product, dosage and notes (D1);
3. add ``custom_activities``, anchored to a week counted from the block's
   start date or to a phenology stage plus an offset (D2);
4. move any activity whose key has a date override for this block (C2, C4).

No DB or IO, so the rules are unit-tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from app.modules.plan_templates.apply import resolve_schedule, stage_start_date

EDITABLE_FIELDS = (
    "product_name",
    "dosage",
    "notes",
    "product_name_ar",
    "dosage_ar",
    "notes_ar",
)


@dataclass(frozen=True)
class AllocatedActivity:
    activity_key: str
    source: str  # "template" | "custom"
    template_activity_id: UUID | None
    activity_type: str
    title: str | None
    title_ar: str | None
    scheduled_date: date
    duration_days: int
    anchored_stage_code: str | None
    product_name: str | None
    dosage: str | None
    notes: str | None
    start_time: Any
    date_overridden: bool
    default_date: date
    # D20: the catalogue input and structured dose of a manual activity.
    input_id: Any = None
    dose_value: Any = None
    dose_value_max: Any = None
    dose_unit: str | None = None


def custom_key(custom: dict[str, Any]) -> str:
    """Custom activity keys are stored as ``custom:<id>`` so they can never
    collide with a manual activity code."""
    key = str(custom["key"])
    return key if key.startswith("custom:") else f"custom:{key}"


def _custom_date(
    custom: dict[str, Any],
    *,
    stages_by_code: dict[str, dict[str, Any]],
    block_start_date: date,
    planting_date: date | None,
    is_perennial: bool,
    season_year: int,
) -> tuple[date | None, str | None]:
    """Date and anchored stage for a custom activity, or (None, None) when its
    stage can't be resolved for this block."""
    offset = int(custom.get("offset_days") or 0)
    if custom.get("anchor") == "stage":
        stage = stages_by_code.get(str(custom.get("stage_code")))
        if stage is None:
            return None, None
        start = stage_start_date(
            stage["advance"],
            is_perennial=is_perennial,
            planting_date=planting_date,
            season_year=season_year,
        )
        if start is None:
            return None, None
        return start + timedelta(days=offset), str(custom.get("stage_code"))
    week = max(1, int(custom.get("week") or 1))
    return block_start_date + timedelta(days=(week - 1) * 7 + offset), None


def resolve_allocation(
    *,
    activities: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
    stages: list[dict[str, Any]] | None,
    block_start_date: date,
    planting_date: date | None,
    is_perennial: bool,
    season_year: int,
    excluded_codes: set[str],
    activity_edits: dict[str, dict[str, Any]],
    custom_activities: list[dict[str, Any]],
    overrides: dict[str, str],
) -> tuple[list[AllocatedActivity], list[dict[str, Any]]]:
    """Return (activities, skipped) for one block, sorted by date."""
    included = [a for a in activities if a.get("code") not in excluded_codes]
    by_id = {a["id"]: a for a in included}
    resolved, skipped = resolve_schedule(
        activities=included,
        milestones=milestones,
        stages=stages,
        block_start_date=block_start_date,
        planting_date=planting_date,
        is_perennial=is_perennial,
        season_year=season_year,
    )

    out: list[AllocatedActivity] = []
    for r in resolved:
        key = str(r.activity_code or by_id[r.template_activity_id].get("code"))
        edits = activity_edits.get(key, {})
        override = overrides.get(key)
        out.append(
            AllocatedActivity(
                activity_key=key,
                source="template",
                template_activity_id=r.template_activity_id,
                activity_type=r.activity_type,
                title=r.title,
                title_ar=r.title_ar,
                scheduled_date=date.fromisoformat(override) if override else r.scheduled_date,
                duration_days=r.duration_days,
                anchored_stage_code=r.anchored_stage_code,
                product_name=edits.get("product_name", r.product_name),
                dosage=edits.get("dosage", r.dosage),
                notes=edits.get("notes", r.notes),
                start_time=r.start_time,
                date_overridden=bool(override),
                default_date=r.scheduled_date,
                input_id=r.input_id,
                dose_value=r.dose_value,
                dose_value_max=r.dose_value_max,
                dose_unit=r.dose_unit,
            )
        )

    stages_by_code = {s["code"]: s for s in (stages or [])}
    for c in custom_activities:
        key = custom_key(c)
        default, stage_code = _custom_date(
            c,
            stages_by_code=stages_by_code,
            block_start_date=block_start_date,
            planting_date=planting_date,
            is_perennial=is_perennial,
            season_year=season_year,
        )
        if default is None:
            skipped.append(
                {
                    "activity_key": key,
                    "stage_code": c.get("stage_code"),
                    "reason": "stage_date_unresolvable",
                }
            )
            continue
        override = overrides.get(key)
        out.append(
            AllocatedActivity(
                activity_key=key,
                source="custom",
                template_activity_id=None,
                activity_type=str(c["activity_type"]),
                title=c.get("title"),
                title_ar=c.get("title_ar"),
                scheduled_date=date.fromisoformat(override) if override else default,
                duration_days=max(1, int(c.get("duration_days") or 1)),
                anchored_stage_code=stage_code,
                product_name=c.get("product_name"),
                dosage=c.get("dosage"),
                notes=c.get("notes"),
                start_time=None,
                date_overridden=bool(override),
                default_date=default,
            )
        )

    out.sort(key=lambda a: (a.scheduled_date, a.activity_key))
    return out, skipped


__all__ = ["EDITABLE_FIELDS", "AllocatedActivity", "custom_key", "resolve_allocation"]
