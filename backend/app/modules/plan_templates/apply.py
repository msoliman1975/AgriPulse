"""Pure resolver: a plan template + a block's context -> dated activities.

Kept pure (no DB/IO) so the anchor math is unit-tested fast. The service
feeds it the template tree, the block's start date / planting date /
season year, and the block's resolved phenology stages.

Anchors:
  * ``start``     -> block_start_date + offset_days
  * ``milestone`` -> block_start_date + milestone.day_from_start + offset_days
  * ``stage``     -> stage's resolved start date + offset_days, where the
    stage start is:
      - perennial: the stage's ``calendar_doy`` start mapped onto season_year
      - annual:    planting_date + ``days_from_planting`` start_day
    GDD-based / manual stages (and unknown refs) can't resolve to a date in
    V1 and are reported as skipped, not scheduled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ResolvedActivity:
    template_activity_id: UUID
    activity_type: str
    scheduled_date: date
    duration_days: int
    anchored_stage_code: str | None
    product_name: str | None
    dosage: str | None
    notes: str | None
    start_time: Any  # datetime.time | None


def _stage_start_date(
    advance: dict[str, Any],
    *,
    is_perennial: bool,
    planting_date: date | None,
    season_year: int,
) -> date | None:
    mode = advance.get("mode")
    if is_perennial and mode == "calendar_doy":
        month, day = (int(p) for p in str(advance["start_doy"]).split("-"))
        return date(season_year, month, day)
    if not is_perennial and mode == "days_from_planting" and planting_date is not None:
        return planting_date + timedelta(days=int(advance["start_day"]))
    # gdd_from_planting / manual / mode-cycle mismatch / missing planting_date
    return None


def resolve_schedule(
    *,
    activities: list[dict[str, Any]],
    milestones: list[dict[str, Any]],
    stages: list[dict[str, Any]] | None,
    block_start_date: date,
    planting_date: date | None,
    is_perennial: bool,
    season_year: int,
) -> tuple[list[ResolvedActivity], list[dict[str, Any]]]:
    """Return (resolved, skipped). ``skipped`` carries a reason per dropped
    activity so the preview/apply result can explain gaps."""
    milestones_by_id = {m["id"]: m for m in milestones}
    stages_by_code = {s["code"]: s for s in (stages or [])}
    resolved: list[ResolvedActivity] = []
    skipped: list[dict[str, Any]] = []

    for a in activities:
        anchor = a["anchor"]
        offset = int(a.get("offset_days", 0))
        anchored_stage: str | None = None

        if anchor == "start":
            sched = block_start_date + timedelta(days=offset)
        elif anchor == "milestone":
            milestone = milestones_by_id.get(a.get("milestone_id"))
            if milestone is None:
                skipped.append({"activity_id": a["id"], "reason": "milestone_not_found"})
                continue
            sched = block_start_date + timedelta(days=int(milestone["day_from_start"]) + offset)
        elif anchor == "stage":
            stage = stages_by_code.get(a.get("stage_code"))
            start = (
                _stage_start_date(
                    stage["advance"],
                    is_perennial=is_perennial,
                    planting_date=planting_date,
                    season_year=season_year,
                )
                if stage is not None
                else None
            )
            if start is None:
                reason = "stage_not_in_phenology" if stage is None else "stage_date_unresolvable"
                skipped.append(
                    {"activity_id": a["id"], "stage_code": a.get("stage_code"), "reason": reason}
                )
                continue
            sched = start + timedelta(days=offset)
            anchored_stage = a.get("stage_code")
        else:  # pragma: no cover - CHECK constraint guards this
            skipped.append({"activity_id": a["id"], "reason": f"unknown_anchor:{anchor}"})
            continue

        resolved.append(
            ResolvedActivity(
                template_activity_id=a["id"],
                activity_type=a["activity_type"],
                scheduled_date=sched,
                duration_days=int(a.get("duration_days", 1)),
                anchored_stage_code=anchored_stage,
                product_name=a.get("product_name"),
                dosage=a.get("dosage"),
                notes=a.get("notes"),
                start_time=a.get("start_time"),
            )
        )

    return resolved, skipped


__all__ = ["ResolvedActivity", "resolve_schedule"]
