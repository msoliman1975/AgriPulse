"""Async DB access for the plan-templates catalog (public schema).

E1: read projections (list + full tree). Write (whole-tree upsert) and
the apply engine land in PR-E2/E3.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.models import (
    PlanTemplate,
    PlanTemplateActivity,
    PlanTemplateMilestone,
)


def _template_dict(t: PlanTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "crop_path": t.crop_path,
        "crop_id": t.crop_id,
        "country": t.country,
        "region": t.region,
        "description": t.description,
        "status": t.status,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _milestone_dict(m: PlanTemplateMilestone) -> dict[str, Any]:
    return {
        "id": m.id,
        "code": m.code,
        "name": m.name,
        "day_from_start": m.day_from_start,
        "sort_order": m.sort_order,
    }


def _activity_dict(a: PlanTemplateActivity) -> dict[str, Any]:
    return {
        "id": a.id,
        "activity_type": a.activity_type,
        "anchor": a.anchor,
        "milestone_id": a.milestone_id,
        "stage_code": a.stage_code,
        "offset_days": a.offset_days,
        "duration_days": a.duration_days,
        "product_name": a.product_name,
        "dosage": a.dosage,
        "notes": a.notes,
        "start_time": a.start_time,
        "sort_order": a.sort_order,
    }


class PlanTemplatesRepository:
    """Public-schema catalog access. The service is the only consumer."""

    def __init__(self, *, public_session: AsyncSession) -> None:
        self._public = public_session

    async def list_templates(
        self, *, status_filter: tuple[str, ...] = (), crop_path: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(PlanTemplate).where(PlanTemplate.deleted_at.is_(None))
        if status_filter:
            stmt = stmt.where(PlanTemplate.status.in_(status_filter))
        if crop_path is not None:
            stmt = stmt.where(PlanTemplate.crop_path == crop_path)
        stmt = stmt.order_by(PlanTemplate.crop_path, PlanTemplate.name)
        rows = (await self._public.execute(stmt)).scalars().all()
        return [_template_dict(r) for r in rows]

    async def get_template(self, *, template_id: UUID) -> PlanTemplate | None:
        return (
            await self._public.execute(
                select(PlanTemplate).where(
                    PlanTemplate.id == template_id, PlanTemplate.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def get_full_tree(self, *, template_id: UUID) -> dict[str, Any] | None:
        template = await self.get_template(template_id=template_id)
        if template is None:
            return None
        milestones = (
            (
                await self._public.execute(
                    select(PlanTemplateMilestone)
                    .where(PlanTemplateMilestone.template_id == template_id)
                    .order_by(
                        PlanTemplateMilestone.sort_order, PlanTemplateMilestone.day_from_start
                    )
                )
            )
            .scalars()
            .all()
        )
        activities = (
            (
                await self._public.execute(
                    select(PlanTemplateActivity)
                    .where(PlanTemplateActivity.template_id == template_id)
                    .order_by(PlanTemplateActivity.sort_order)
                )
            )
            .scalars()
            .all()
        )
        out = _template_dict(template)
        out["milestones"] = [_milestone_dict(m) for m in milestones]
        out["activities"] = [_activity_dict(a) for a in activities]
        return out


__all__ = ["PlanTemplatesRepository"]
