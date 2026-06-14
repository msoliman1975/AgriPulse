"""Plan-templates service: appliable discovery + preview + apply.

Apply materialises the existing ``vegetation_plans`` / ``plan_activities``
from a template, resolving stage-anchored activities against each block's
phenology (the spine). Idempotent per (farm, season): regenerates this
template's still-scheduled rows, preserves manual + completed rows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.plan_templates.apply import resolve_schedule
from app.modules.plan_templates.errors import (
    PlanTemplateConflictError,
    PlanTemplateNotFoundError,
    PlanTemplateValidationError,
)
from app.modules.plan_templates.repository import PlanTemplatesRepository
from app.modules.plan_templates.schemas import PlanTemplateWriteRequest
from app.shared.crop_taxonomy import path_matches


class PlanTemplatesService:
    def __init__(
        self,
        *,
        public_session: AsyncSession,
        tenant_session: AsyncSession | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._public = public_session
        self._tenant = tenant_session
        self._repo = PlanTemplatesRepository(
            public_session=public_session, tenant_session=tenant_session
        )
        self._audit = audit_service or get_audit_service()
        self._log = get_logger(__name__)

    # ---- Reads --------------------------------------------------------

    async def list_templates(
        self, *, status_filter: tuple[str, ...] = (), crop_path: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._repo.list_templates(status_filter=status_filter, crop_path=crop_path)

    async def get_full_tree(self, *, template_id: UUID) -> dict[str, Any]:
        tree = await self._repo.get_full_tree(template_id=template_id)
        if tree is None:
            raise PlanTemplateNotFoundError(template_id)
        return tree

    async def resolve_phenology(self, *, crop_path: str) -> dict[str, Any]:
        """Resolved phenology stages for a crop path (deepest-wins). Powers the
        platform authoring stage-picker so it only offers valid stage codes."""
        is_perennial, stages = await self._repo.resolve_phenology_for_path(crop_path=crop_path)
        return {"crop_path": crop_path, "is_perennial": is_perennial, "stages": stages}

    # ---- Authoring (platform; whole-tree write) -----------------------

    async def _validate_tree(self, payload: PlanTemplateWriteRequest) -> None:
        """Cross-field + stage-existence validation the schema can't express."""
        milestone_codes = [m.code for m in payload.milestones]
        if len(milestone_codes) != len(set(milestone_codes)):
            raise PlanTemplateValidationError(reason="Duplicate milestone codes in template.")
        milestone_set = set(milestone_codes)

        needs_stages = any(a.anchor == "stage" for a in payload.activities)
        stage_codes: set[str] = set()
        if needs_stages:
            _, stages = await self._repo.resolve_phenology_for_path(crop_path=payload.crop_path)
            stage_codes = {str(s["code"]) for s in stages if s.get("code")}

        for idx, a in enumerate(payload.activities):
            if a.anchor == "milestone":
                if not a.milestone_code:
                    raise PlanTemplateValidationError(
                        reason=f"Activity #{idx + 1} anchors to a milestone but has no milestone_code."
                    )
                if a.milestone_code not in milestone_set:
                    raise PlanTemplateValidationError(
                        reason=f"Activity #{idx + 1} references unknown milestone "
                        f"{a.milestone_code!r}."
                    )
            elif a.anchor == "stage":
                if not a.stage_code:
                    raise PlanTemplateValidationError(
                        reason=f"Activity #{idx + 1} anchors to a stage but has no stage_code."
                    )
                if a.stage_code not in stage_codes:
                    raise PlanTemplateValidationError(
                        reason=f"Activity #{idx + 1} references stage {a.stage_code!r} which is not "
                        f"in the resolved phenology for {payload.crop_path!r}."
                    )

    @staticmethod
    def _tree_dicts(
        payload: PlanTemplateWriteRequest,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        milestones = [m.model_dump() for m in payload.milestones]
        activities = [a.model_dump() for a in payload.activities]
        return milestones, activities

    async def create_template(
        self, *, payload: PlanTemplateWriteRequest, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        if await self._repo.get_template_by_code(code=payload.code) is not None:
            raise PlanTemplateConflictError(code=payload.code)
        await self._validate_tree(payload)
        milestones, activities = self._tree_dicts(payload)
        template_id = await self._repo.create_full_tree(
            header=payload.model_dump(exclude={"milestones", "activities"}),
            milestones=milestones,
            activities=activities,
            actor_user_id=actor_user_id,
        )
        return await self.get_full_tree(template_id=template_id)

    async def update_template(
        self, *, template_id: UUID, payload: PlanTemplateWriteRequest, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        template = await self._repo.get_template(template_id=template_id)
        if template is None:
            raise PlanTemplateNotFoundError(template_id)
        if template.code != payload.code:
            clash = await self._repo.get_template_by_code(code=payload.code)
            if clash is not None and clash.id != template_id:
                raise PlanTemplateConflictError(code=payload.code)
        await self._validate_tree(payload)
        milestones, activities = self._tree_dicts(payload)
        await self._repo.replace_full_tree(
            template=template,
            header=payload.model_dump(exclude={"milestones", "activities"}),
            milestones=milestones,
            activities=activities,
            actor_user_id=actor_user_id,
        )
        return await self.get_full_tree(template_id=template_id)

    async def set_status(
        self, *, template_id: UUID, status: str, actor_user_id: UUID | None
    ) -> dict[str, Any]:
        template = await self._repo.get_template(template_id=template_id)
        if template is None:
            raise PlanTemplateNotFoundError(template_id)
        await self._repo.set_status(template=template, status=status, actor_user_id=actor_user_id)
        return await self.get_full_tree(template_id=template_id)

    async def delete_template(self, *, template_id: UUID, actor_user_id: UUID | None) -> None:
        template = await self._repo.get_template(template_id=template_id)
        if template is None:
            raise PlanTemplateNotFoundError(template_id)
        await self._repo.soft_delete(template=template, actor_user_id=actor_user_id)

    async def list_appliable(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        """Published templates that match at least one of the farm's current
        block crops, each with the blocks it fits + planting-date defaults."""
        templates = await self._repo.list_templates(status_filter=("published",))
        block_crops = await self._repo.list_current_block_crops(farm_id=farm_id)
        out: list[dict[str, Any]] = []
        for t in templates:
            matching = [
                {
                    "block_id": bc["block_id"],
                    "block_code": bc["block_code"],
                    "crop_path": bc["crop_path"],
                    "planting_date": bc["planting_date"],
                }
                for bc in block_crops
                if path_matches(t["crop_path"], bc["crop_path"])
            ]
            if matching:
                out.append({**t, "matching_blocks": matching})
        return out

    # ---- Resolve (shared by preview + apply) --------------------------

    async def _resolve_for_blocks(
        self,
        *,
        tree: dict[str, Any],
        farm_id: UUID,
        season_year: int,
        blocks: list[Any],
    ) -> list[dict[str, Any]]:
        """Per requested block: hard-gate match, resolve phenology, schedule.

        ``blocks`` items expose ``.block_id`` and ``.start_date``. Returns a
        list of per-block dicts ``{block_id, block_code, crop_path, planting_date,
        matched, resolved, skipped}``.
        """
        bc_by_id = {
            bc["block_id"]: bc for bc in await self._repo.list_current_block_crops(farm_id=farm_id)
        }
        results: list[dict[str, Any]] = []
        for blk in blocks:
            bc = bc_by_id.get(blk.block_id)
            if bc is None or not path_matches(tree["crop_path"], bc["crop_path"]):
                results.append(
                    {
                        "block_id": blk.block_id,
                        "block_code": bc["block_code"] if bc else None,
                        "matched": False,
                        "resolved": [],
                        "skipped": [{"reason": "block_crop_does_not_match_template"}],
                    }
                )
                continue
            is_perennial, stages = await self._repo.resolve_phenology_for_path(
                crop_path=bc["crop_path"]
            )
            resolved, skipped = resolve_schedule(
                activities=tree["activities"],
                milestones=tree["milestones"],
                stages=stages,
                block_start_date=blk.start_date,
                planting_date=bc["planting_date"],
                is_perennial=is_perennial,
                season_year=season_year,
            )
            results.append(
                {
                    "block_id": blk.block_id,
                    "block_code": bc["block_code"],
                    "crop_path": bc["crop_path"],
                    "planting_date": bc["planting_date"],
                    "matched": True,
                    "resolved": resolved,
                    "skipped": skipped,
                }
            )
        return results

    async def preview(
        self, *, template_id: UUID, farm_id: UUID, season_year: int, blocks: list[Any]
    ) -> dict[str, Any]:
        tree = await self.get_full_tree(template_id=template_id)
        per_block = await self._resolve_for_blocks(
            tree=tree, farm_id=farm_id, season_year=season_year, blocks=blocks
        )
        total_activities = sum(len(b["resolved"]) for b in per_block)
        total_skipped = sum(len(b["skipped"]) for b in per_block)
        return {
            "template_id": template_id,
            "blocks": [
                {
                    "block_id": b["block_id"],
                    "block_code": b.get("block_code"),
                    "activities": [
                        {
                            "template_activity_id": a.template_activity_id,
                            "activity_type": a.activity_type,
                            "scheduled_date": a.scheduled_date,
                            "duration_days": a.duration_days,
                            "anchored_stage_code": a.anchored_stage_code,
                        }
                        for a in b["resolved"]
                    ],
                    "skipped": b["skipped"],
                }
                for b in per_block
            ],
            "total_activities": total_activities,
            "total_skipped": total_skipped,
        }

    async def apply(
        self,
        *,
        template_id: UUID,
        farm_id: UUID,
        season_label: str,
        season_year: int,
        blocks: list[Any],
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        tree = await self.get_full_tree(template_id=template_id)
        per_block = await self._resolve_for_blocks(
            tree=tree, farm_id=farm_id, season_year=season_year, blocks=blocks
        )
        plan_id = await self._repo.find_or_create_plan(
            farm_id=farm_id,
            season_label=season_label,
            season_year=season_year,
            template_id=template_id,
            actor_user_id=actor_user_id,
        )
        blocks_applied = 0
        activities_created = 0
        skipped = 0
        for b in per_block:
            skipped += len(b["skipped"])
            if not b["matched"]:
                continue
            await self._repo.delete_template_scheduled(
                plan_id=plan_id, block_id=b["block_id"], template_id=template_id
            )
            for a in b["resolved"]:
                await self._repo.insert_plan_activity(
                    plan_id=plan_id,
                    farm_id=farm_id,
                    block_id=b["block_id"],
                    template_id=template_id,
                    template_activity_id=a.template_activity_id,
                    activity_type=a.activity_type,
                    scheduled_date=a.scheduled_date,
                    duration_days=a.duration_days,
                    anchored_stage_code=a.anchored_stage_code,
                    product_name=a.product_name,
                    dosage=a.dosage,
                    notes=a.notes,
                    start_time=a.start_time,
                    actor_user_id=actor_user_id,
                )
                activities_created += 1
            blocks_applied += 1
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plan_templates.applied",
            actor_user_id=actor_user_id,
            subject_kind="vegetation_plan",
            subject_id=plan_id,
            farm_id=farm_id,
            details={
                "template_id": str(template_id),
                "blocks_applied": blocks_applied,
                "activities_created": activities_created,
            },
        )
        return {
            "template_id": template_id,
            "plan_id": plan_id,
            "blocks_applied": blocks_applied,
            "activities_created": activities_created,
            "skipped": skipped,
        }


def get_plan_templates_service(
    *,
    public_session: AsyncSession,
    tenant_session: AsyncSession | None = None,
    audit_service: AuditService | None = None,
) -> PlanTemplatesService:
    return PlanTemplatesService(
        public_session=public_session,
        tenant_session=tenant_session,
        audit_service=audit_service,
    )


__all__ = ["PlanTemplatesService", "get_plan_templates_service"]
