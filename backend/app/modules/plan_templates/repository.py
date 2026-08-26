"""Async DB access for the plan-templates catalog (public schema).

E1: read projections (list + full tree). Write (whole-tree upsert) and
the apply engine land in PR-E2/E3.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.models import (
    PlanTemplate,
    PlanTemplateActivity,
    PlanTemplateMilestone,
)
from app.shared.db.ids import uuid7


def _template_dict(t: PlanTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "name_ar": t.name_ar,
        "crop_path": t.crop_path,
        "crop_id": t.crop_id,
        "country": t.country,
        "region": t.region,
        "description": t.description,
        "description_ar": t.description_ar,
        "status": t.status,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _milestone_dict(m: PlanTemplateMilestone) -> dict[str, Any]:
    return {
        "id": m.id,
        "code": m.code,
        "name": m.name,
        "name_ar": m.name_ar,
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

    def __init__(
        self, *, public_session: AsyncSession, tenant_session: AsyncSession | None = None
    ) -> None:
        self._public = public_session
        self._tenant = tenant_session

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

    # ---- Authoring writes (public) ------------------------------------

    async def get_template_by_code(self, *, code: str) -> PlanTemplate | None:
        return (
            await self._public.execute(
                select(PlanTemplate).where(
                    PlanTemplate.code == code, PlanTemplate.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def _crop_id_for_path(self, *, crop_path: str) -> UUID | None:
        segments = [s for s in crop_path.split(".") if s]
        if not segments:
            return None
        row = (
            await self._public.execute(
                text("SELECT id FROM public.crops WHERE code = :c AND deleted_at IS NULL"),
                {"c": segments[0]},
            )
        ).first()
        return row.id if row is not None else None

    async def _insert_children(
        self,
        *,
        template_id: UUID,
        milestones: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        actor_user_id: UUID | None,
    ) -> None:
        """Insert milestones then activities, resolving each milestone-anchored
        activity's ``milestone_code`` to the freshly-minted milestone id."""
        code_to_id: dict[str, UUID] = {}
        for m in milestones:
            mid = uuid7()
            code_to_id[m["code"]] = mid
            self._public.add(
                PlanTemplateMilestone(
                    id=mid,
                    template_id=template_id,
                    code=m["code"],
                    name=m["name"],
                    name_ar=m.get("name_ar"),
                    day_from_start=int(m["day_from_start"]),
                    sort_order=int(m.get("sort_order", 0)),
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
            )
        # Persist milestones before the activities that FK-reference them so the
        # constraint holds regardless of unit-of-work insert ordering.
        if milestones:
            await self._public.flush()
        for a in activities:
            milestone_id: UUID | None = None
            if a.get("anchor") == "milestone":
                mcode = a.get("milestone_code")
                if mcode is not None:
                    milestone_id = code_to_id.get(str(mcode))
            self._public.add(
                PlanTemplateActivity(
                    id=uuid7(),
                    template_id=template_id,
                    activity_type=a["activity_type"],
                    anchor=a["anchor"],
                    milestone_id=milestone_id,
                    stage_code=a.get("stage_code") if a.get("anchor") == "stage" else None,
                    offset_days=int(a.get("offset_days", 0)),
                    duration_days=int(a.get("duration_days", 1)),
                    product_name=a.get("product_name"),
                    dosage=a.get("dosage"),
                    notes=a.get("notes"),
                    start_time=a.get("start_time"),
                    sort_order=int(a.get("sort_order", 0)),
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
            )

    async def create_full_tree(
        self,
        *,
        header: dict[str, Any],
        milestones: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        actor_user_id: UUID | None,
    ) -> UUID:
        template_id = uuid7()
        crop_id = await self._crop_id_for_path(crop_path=header["crop_path"])
        self._public.add(
            PlanTemplate(
                id=template_id,
                code=header["code"],
                name=header["name"],
                name_ar=header.get("name_ar"),
                crop_path=header["crop_path"],
                crop_id=crop_id,
                country=header.get("country"),
                region=header.get("region"),
                description=header.get("description"),
                description_ar=header.get("description_ar"),
                status="draft",
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
        )
        await self._insert_children(
            template_id=template_id,
            milestones=milestones,
            activities=activities,
            actor_user_id=actor_user_id,
        )
        await self._public.flush()
        return template_id

    async def replace_full_tree(
        self,
        *,
        template: PlanTemplate,
        header: dict[str, Any],
        milestones: list[dict[str, Any]],
        activities: list[dict[str, Any]],
        actor_user_id: UUID | None,
    ) -> None:
        """Atomically replace a template's header + children. ``status`` is not
        touched here (publish/archive are separate transitions)."""
        await self._public.execute(
            delete(PlanTemplateActivity).where(PlanTemplateActivity.template_id == template.id)
        )
        await self._public.execute(
            delete(PlanTemplateMilestone).where(PlanTemplateMilestone.template_id == template.id)
        )
        template.code = header["code"]
        template.name = header["name"]
        template.name_ar = header.get("name_ar")
        template.crop_path = header["crop_path"]
        template.crop_id = await self._crop_id_for_path(crop_path=header["crop_path"])
        template.country = header.get("country")
        template.region = header.get("region")
        template.description = header.get("description")
        template.description_ar = header.get("description_ar")
        template.updated_by = actor_user_id
        await self._public.flush()
        await self._insert_children(
            template_id=template.id,
            milestones=milestones,
            activities=activities,
            actor_user_id=actor_user_id,
        )
        await self._public.flush()

    async def set_status(
        self, *, template: PlanTemplate, status: str, actor_user_id: UUID | None
    ) -> None:
        template.status = status
        template.updated_by = actor_user_id
        await self._public.flush()

    async def soft_delete(self, *, template: PlanTemplate, actor_user_id: UUID | None) -> None:
        """Retire = archive + stamp ``deleted_at`` so the code frees up."""
        template.status = "archived"
        template.updated_by = actor_user_id
        await self._public.execute(
            text("UPDATE public.plan_templates SET deleted_at = now() WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": template.id},
        )
        await self._public.flush()

    # ---- Catalog phenology resolution (public) ------------------------

    async def resolve_phenology_for_path(
        self, *, crop_path: str
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Return ``(is_perennial, stages)`` for a crop path, resolving the
        phenology deepest-wins (strain → variety → crop). ``stages`` is the
        ``stages`` list (possibly empty)."""
        segments = [s for s in crop_path.split(".") if s]
        if not segments:
            return False, []
        crop = (
            await self._public.execute(
                text(
                    "SELECT id, is_perennial, phenology_stages "
                    "FROM public.crops WHERE code = :c AND deleted_at IS NULL"
                ),
                {"c": segments[0]},
            )
        ).first()
        if crop is None:
            return False, []
        resolved = crop.phenology_stages
        if len(segments) >= 2:
            variety = (
                await self._public.execute(
                    text(
                        "SELECT phenology_stages_override FROM public.crop_varieties "
                        "WHERE path = :p AND deleted_at IS NULL"
                    ),
                    {"p": f"{segments[0]}.{segments[1]}"},
                )
            ).first()
            if variety is not None and variety.phenology_stages_override is not None:
                resolved = variety.phenology_stages_override
        if len(segments) >= 3:
            strain = (
                await self._public.execute(
                    text(
                        "SELECT phenology_stages_override FROM public.crop_variety_strains "
                        "WHERE path = :p AND deleted_at IS NULL"
                    ),
                    {"p": f"{segments[0]}.{segments[1]}.{segments[2]}"},
                )
            ).first()
            if strain is not None and strain.phenology_stages_override is not None:
                resolved = strain.phenology_stages_override
        stages = (resolved or {}).get("stages") or []
        return bool(crop.is_perennial), stages

    # ---- Apply (tenant) -----------------------------------------------

    async def list_current_block_crops(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        """Current block_crops for the farm with the fields apply needs."""
        assert self._tenant is not None
        rows = (
            (
                await self._tenant.execute(
                    text(
                        """
                    SELECT bc.block_id, b.code AS block_code, bc.crop_path,
                           bc.planting_date
                    FROM block_crops bc
                    JOIN blocks b ON b.id = bc.block_id AND b.deleted_at IS NULL
                    WHERE b.farm_id = :farm
                      AND bc.is_current = TRUE
                      AND bc.deleted_at IS NULL
                      AND bc.crop_path <> ''
                    ORDER BY b.code
                    """
                    ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                    {"farm": farm_id},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def find_or_create_plan(
        self,
        *,
        farm_id: UUID,
        season_label: str,
        season_year: int,
        template_id: UUID,
        actor_user_id: UUID | None,
    ) -> UUID:
        assert self._tenant is not None
        existing = (
            await self._tenant.execute(
                text(
                    "SELECT id FROM vegetation_plans "
                    "WHERE farm_id = :farm AND season_label = :label "
                    "  AND season_year = :year AND deleted_at IS NULL "
                    "LIMIT 1"
                ).bindparams(bindparam("farm", type_=PG_UUID(as_uuid=True))),
                {"farm": farm_id, "label": season_label, "year": season_year},
            )
        ).first()
        if existing is not None:
            await self._tenant.execute(
                text(
                    "UPDATE vegetation_plans SET applied_template_id = :tpl, updated_by = :actor "
                    "WHERE id = :id"
                ).bindparams(
                    bindparam("tpl", type_=PG_UUID(as_uuid=True)),
                    bindparam("actor", type_=PG_UUID(as_uuid=True)),
                    bindparam("id", type_=PG_UUID(as_uuid=True)),
                ),
                {"tpl": template_id, "actor": actor_user_id, "id": existing.id},
            )
            return existing.id
        plan_id = uuid7()
        await self._tenant.execute(
            text(
                "INSERT INTO vegetation_plans "
                "(id, farm_id, season_label, season_year, status, applied_template_id, "
                " created_by, updated_by) "
                "VALUES (:id, :farm, :label, :year, 'active', :tpl, :actor, :actor)"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("tpl", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "id": plan_id,
                "farm": farm_id,
                "label": season_label,
                "year": season_year,
                "tpl": template_id,
                "actor": actor_user_id,
            },
        )
        return plan_id

    async def delete_template_scheduled(
        self, *, plan_id: UUID, block_id: UUID, template_id: UUID
    ) -> int:
        """Idempotent regen: drop this template's still-scheduled rows for the
        block. Preserves manual rows + completed/in-progress template rows."""
        assert self._tenant is not None
        res = await self._tenant.execute(
            text(
                "DELETE FROM plan_activities "
                "WHERE plan_id = :plan AND block_id = :block "
                "  AND applied_template_id = :tpl AND status = 'scheduled' "
                "  AND source = 'template'"
            ).bindparams(
                bindparam("plan", type_=PG_UUID(as_uuid=True)),
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("tpl", type_=PG_UUID(as_uuid=True)),
            ),
            {"plan": plan_id, "block": block_id, "tpl": template_id},
        )
        return int(getattr(res, "rowcount", 0) or 0)

    async def insert_plan_activity(
        self,
        *,
        plan_id: UUID,
        farm_id: UUID,
        block_id: UUID,
        template_id: UUID,
        template_activity_id: UUID,
        activity_type: str,
        scheduled_date: date,
        duration_days: int,
        anchored_stage_code: str | None,
        product_name: str | None,
        dosage: str | None,
        notes: str | None,
        start_time: Any,
        actor_user_id: UUID | None,
    ) -> None:
        assert self._tenant is not None
        await self._tenant.execute(
            text(
                """
                INSERT INTO plan_activities
                    (plan_id, farm_id, block_id, activity_type, scheduled_date,
                     duration_days, start_time, product_name, dosage, notes,
                     status, source, applied_template_id, template_activity_id,
                     anchored_stage_code, created_by, updated_by)
                VALUES
                    (:plan, :farm, :block, :atype, :sched, :dur, :stime, :pname,
                     :dosage, :notes, 'scheduled', 'template', :tpl, :tact,
                     :stage, :actor, :actor)
                """
            ).bindparams(
                bindparam("plan", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("tpl", type_=PG_UUID(as_uuid=True)),
                bindparam("tact", type_=PG_UUID(as_uuid=True)),
                bindparam("actor", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "plan": plan_id,
                "farm": farm_id,
                "block": block_id,
                "atype": activity_type,
                "sched": scheduled_date,
                "dur": duration_days,
                "stime": start_time,
                "pname": product_name,
                "dosage": dosage,
                "notes": notes,
                "tpl": template_id,
                "tact": template_activity_id,
                "stage": anchored_stage_code,
                "actor": actor_user_id,
            },
        )


__all__ = ["PlanTemplatesRepository"]
