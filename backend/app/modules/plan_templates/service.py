"""Plan-templates service: appliable discovery + preview + apply.

Apply materialises the existing ``vegetation_plans`` / ``plan_activities``
from a template, resolving stage-anchored activities against each block's
phenology (the spine). Idempotent per (farm, season): regenerates this
template's still-scheduled rows, preserves manual + completed rows.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.plan_templates.allocation import resolve_allocation
from app.modules.plan_templates.apply import format_dose, resolve_schedule
from app.modules.plan_templates.errors import (
    AllocationBlocksRejectedError,
    AllocationNotFoundError,
    PlanTemplateConflictError,
    PlanTemplateNotFoundError,
    PlanTemplateValidationError,
)
from app.modules.plan_templates.repository import PlanTemplatesRepository
from app.modules.plan_templates.revisions import diff_snapshots, snapshot_of
from app.modules.plan_templates.schemas import AllocationWriteRequest, PlanTemplateWriteRequest
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
        activity_codes = [a.code for a in payload.activities if a.code]
        if len(activity_codes) != len(set(activity_codes)):
            raise PlanTemplateValidationError(reason="Duplicate activity codes in template.")
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
        assign_activity_codes(activities)
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
        snapshot = None
        if status == "published":
            snapshot = snapshot_of(await self.get_full_tree(template_id=template_id))
        await self._repo.set_status(
            template=template, status=status, actor_user_id=actor_user_id, snapshot=snapshot
        )
        return await self.get_full_tree(template_id=template_id)

    async def delete_template(self, *, template_id: UUID, actor_user_id: UUID | None) -> None:
        template = await self._repo.get_template(template_id=template_id)
        if template is None:
            raise PlanTemplateNotFoundError(template_id)
        await self._repo.soft_delete(template=template, actor_user_id=actor_user_id)

    # ---- Operation manual reads (tenant catalog + platform preview) ---------

    async def list_catalog(self, *, crop: str | None = None) -> list[dict[str, Any]]:
        """Published manuals only (E4), optionally for one crop (first path
        segment), each with its activity count."""
        templates = await self._repo.list_templates(status_filter=("published",))
        if crop:
            templates = [t for t in templates if t["crop_path"].split(".")[0] == crop]
        counts = await self._repo.count_activities(template_ids=[t["id"] for t in templates])
        return [{**t, "activity_count": counts.get(t["id"], 0)} for t in templates]

    async def variety_phenology(self, *, crop_path: str) -> list[dict[str, Any]]:
        """Resolved stages for each variety a manual applies to (H5).

        A crop-level manual covers every active variety of the crop, plus the
        crop's own calendar for blocks without a variety. A variety-level
        manual covers that variety only.
        """
        segments = [s for s in crop_path.split(".") if s]
        if not segments:
            return []
        out: list[dict[str, Any]] = []
        if len(segments) == 1:
            is_perennial, stages = await self._repo.resolve_phenology_for_path(
                crop_path=segments[0]
            )
            out.append(
                {
                    "path": segments[0],
                    "name_en": None,
                    "name_ar": None,
                    "is_perennial": is_perennial,
                    "stages": stages,
                }
            )
        prefix = ".".join(segments[:2])
        for v in await self._repo.list_varieties(crop_code=segments[0]):
            if len(segments) >= 2 and v["path"] != prefix:
                continue
            is_perennial, stages = await self._repo.resolve_phenology_for_path(crop_path=v["path"])
            out.append({**v, "is_perennial": is_perennial, "stages": stages})
        return out

    async def get_manual(self, *, template_id: UUID, published_only: bool) -> dict[str, Any]:
        """The full manual with its resolved stages and per-variety stages.
        Farms only ever see published manuals (E4)."""
        tree = await self.get_full_tree(template_id=template_id)
        if published_only and tree["status"] != "published":
            raise PlanTemplateNotFoundError(template_id)
        is_perennial, stages = await self._repo.resolve_phenology_for_path(
            crop_path=tree["crop_path"]
        )
        return {
            **tree,
            "is_perennial": is_perennial,
            "stages": stages,
            "varieties": await self.variety_phenology(crop_path=tree["crop_path"]),
        }

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
                            "activity_code": a.activity_code,
                            "activity_type": a.activity_type,
                            "title": a.title,
                            "title_ar": a.title_ar,
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
        input_names = await self._repo.input_names(
            {a.input_id for b in per_block for a in b["resolved"] if a.input_id}
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
                    title=a.title,
                    title_ar=a.title_ar,
                    scheduled_date=a.scheduled_date,
                    duration_days=a.duration_days,
                    anchored_stage_code=a.anchored_stage_code,
                    # Screens that read only the free-text fields still show
                    # the input and its dose (D20): fill them when empty.
                    product_name=a.product_name or input_names.get(a.input_id),
                    dosage=a.dosage or format_dose(a.dose_value, a.dose_value_max, a.dose_unit),
                    notes=a.notes,
                    start_time=a.start_time,
                    actor_user_id=actor_user_id,
                    input_id=a.input_id,
                    dose_value=a.dose_value,
                    dose_value_max=a.dose_value_max,
                    dose_unit=a.dose_unit,
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

    # ---- Saved plans (Agri Operation allocations; PR 3) ---------------------

    async def _resolve_allocation(
        self, *, tree: dict[str, Any], farm_id: UUID, payload: AllocationWriteRequest
    ) -> dict[str, Any]:
        """Per block: crop gate (C3), phenology, then the allocation resolver."""
        bc_by_id = {
            bc["block_id"]: bc for bc in await self._repo.list_current_block_crops(farm_id=farm_id)
        }
        excluded = set(payload.excluded_codes)
        edits = {
            code: e.model_dump(exclude_unset=True) for code, e in payload.activity_edits.items()
        }
        customs = [c.model_dump() for c in payload.custom_activities]
        manual_codes = {a["code"] for a in tree["activities"]}
        referenced = set(excluded) | set(edits)
        for per_block in payload.date_overrides.values():
            referenced |= {k for k in per_block if not k.startswith("custom:")}

        blocks: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for blk in payload.blocks:
            bc = bc_by_id.get(blk.block_id)
            if bc is None or not path_matches(tree["crop_path"], bc["crop_path"]):
                rejected.append(
                    {
                        "block_id": blk.block_id,
                        "block_code": bc["block_code"] if bc else None,
                        "crop_path": bc["crop_path"] if bc else None,
                        "reason": "block_crop_does_not_match_manual",
                    }
                )
                continue
            is_perennial, stages = await self._repo.resolve_phenology_for_path(
                crop_path=bc["crop_path"]
            )
            overrides = {
                key: d.isoformat()
                for key, d in payload.date_overrides.get(blk.block_id, {}).items()
            }
            activities, skipped = resolve_allocation(
                activities=tree["activities"],
                milestones=tree["milestones"],
                stages=stages,
                block_start_date=blk.start_date,
                planting_date=bc["planting_date"],
                is_perennial=is_perennial,
                season_year=payload.season_year,
                excluded_codes=excluded,
                activity_edits=edits,
                custom_activities=customs,
                overrides=overrides,
            )
            blocks.append(
                {
                    "block_id": blk.block_id,
                    "block_code": bc["block_code"],
                    "crop_path": bc["crop_path"],
                    "start_date": blk.start_date,
                    "activities": activities,
                    "skipped": skipped,
                }
            )
        return {
            "template_id": tree["id"],
            "blocks": blocks,
            "rejected_blocks": rejected,
            "missing_codes": sorted(referenced - manual_codes),
            "total_activities": sum(len(b["activities"]) for b in blocks),
        }

    async def preview_allocation(
        self, *, farm_id: UUID, payload: AllocationWriteRequest
    ) -> dict[str, Any]:
        """The dated schedule a saved plan would produce, without writing (C2)."""
        tree = await self.get_full_tree(template_id=payload.template_id)
        result = await self._resolve_allocation(tree=tree, farm_id=farm_id, payload=payload)
        result["blocks"] = [
            {**b, "activities": [a.__dict__ for a in b["activities"]]} for b in result["blocks"]
        ]
        return result

    async def save_allocation(
        self,
        *,
        farm_id: UUID,
        allocation_id: UUID | None,
        payload: AllocationWriteRequest,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> dict[str, Any]:
        """Create or replace a saved plan, then apply it: soft-delete its
        still-scheduled rows and write the new schedule. Rows already started,
        completed or skipped stay and are not recreated."""
        previous_template_id: UUID | None = None
        if allocation_id is not None:
            existing = await self._repo.get_allocation(allocation_id=allocation_id)
            if existing is None or existing["farm_id"] != farm_id:
                raise AllocationNotFoundError(allocation_id)
            previous_template_id = existing["template_id"]
        tree = await self.get_full_tree(template_id=payload.template_id)
        # A saved plan can be re-applied on a manual that was since archived,
        # but a plan can only start from (or switch to) a published manual.
        is_new_manual = previous_template_id != payload.template_id
        if is_new_manual and tree["status"] != "published":
            raise PlanTemplateNotFoundError(payload.template_id)
        resolved = await self._resolve_allocation(tree=tree, farm_id=farm_id, payload=payload)
        if resolved["rejected_blocks"]:
            raise AllocationBlocksRejectedError(blocks=resolved["rejected_blocks"])

        plan_id = await self._repo.find_or_create_plan(
            farm_id=farm_id,
            season_label=payload.season_label,
            season_year=payload.season_year,
            template_id=payload.template_id,
            actor_user_id=actor_user_id,
        )
        allocation_id = await self._repo.save_allocation(
            allocation_id=allocation_id,
            farm_id=farm_id,
            plan_id=plan_id,
            fields={
                "tpl": payload.template_id,
                "rev": int(tree.get("revision") or 0),
                "label": payload.season_label,
                "year": payload.season_year,
                "mode": payload.start_mode,
                "blocks": json.dumps(
                    [
                        {"block_id": str(b.block_id), "start_date": b.start_date.isoformat()}
                        for b in payload.blocks
                    ]
                ),
                "excluded": list(payload.excluded_codes),
                "edits": json.dumps(
                    {
                        code: e.model_dump(exclude_unset=True)
                        for code, e in payload.activity_edits.items()
                    }
                ),
                "customs": json.dumps([c.model_dump() for c in payload.custom_activities]),
                "snapshot": json.dumps(snapshot_of(tree), default=str),
                "overrides": json.dumps(
                    {
                        str(block_id): {k: d.isoformat() for k, d in per_block.items()}
                        for block_id, per_block in payload.date_overrides.items()
                    }
                ),
            },
            actor_user_id=actor_user_id,
        )

        await self._repo.soft_delete_allocation_scheduled(
            allocation_id=allocation_id, actor_user_id=actor_user_id
        )
        kept_keys = await self._repo.allocation_kept_keys(allocation_id=allocation_id)
        input_names = await self._repo.input_names(
            {a.input_id for b in resolved["blocks"] for a in b["activities"] if a.input_id}
        )
        created = kept = skipped = 0
        for b in resolved["blocks"]:
            skipped += len(b["skipped"])
            for a in b["activities"]:
                if (b["block_id"], a.activity_key) in kept_keys:
                    kept += 1
                    continue
                # Same fallbacks as a template apply (D20): the input's name and
                # the structured dose fill in a missing product or dosage text.
                row = replace(
                    a,
                    product_name=a.product_name or input_names.get(a.input_id),
                    dosage=a.dosage or format_dose(a.dose_value, a.dose_value_max, a.dose_unit),
                )
                await self._repo.insert_allocated_activity(
                    allocation_id=allocation_id,
                    plan_id=plan_id,
                    farm_id=farm_id,
                    block_id=b["block_id"],
                    template_id=payload.template_id,
                    activity=row,
                    actor_user_id=actor_user_id,
                )
                created += 1

        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plan_allocations.applied",
            actor_user_id=actor_user_id,
            subject_kind="plan_allocation",
            subject_id=allocation_id,
            farm_id=farm_id,
            details={
                "template_id": str(payload.template_id),
                "template_revision": int(tree.get("revision") or 0),
                "blocks": len(resolved["blocks"]),
                "activities_created": created,
                "activities_kept": kept,
                "excluded_codes": len(payload.excluded_codes),
                "custom_activities": len(payload.custom_activities),
            },
        )
        return {
            "allocation": await self.get_allocation(farm_id=farm_id, allocation_id=allocation_id),
            "activities_created": created,
            "activities_kept": kept,
            "skipped": skipped,
        }

    async def _allocation_view(self, row: dict[str, Any]) -> dict[str, Any]:
        template = await self._repo.get_template(template_id=row["template_id"])
        return {
            **row,
            "template_code": template.code if template else None,
            "template_name": template.name if template else None,
            "template_name_ar": template.name_ar if template else None,
            "crop_path": template.crop_path if template else None,
            # B4: the manual was published again after this plan was applied.
            "manual_updated": bool(
                template is not None and (template.revision or 0) > row["template_revision"]
            ),
        }

    async def get_allocation(self, *, farm_id: UUID, allocation_id: UUID) -> dict[str, Any]:
        row = await self._repo.get_allocation(allocation_id=allocation_id)
        if row is None or row["farm_id"] != farm_id:
            raise AllocationNotFoundError(allocation_id)
        return await self._allocation_view(row)

    async def list_allocations(self, *, farm_id: UUID) -> list[dict[str, Any]]:
        return [
            await self._allocation_view(r)
            for r in await self._repo.list_allocations(farm_id=farm_id)
        ]

    async def manual_changes(self, *, farm_id: UUID, allocation_id: UUID) -> dict[str, Any]:
        """What changed in the manual since this saved plan was applied (B4)."""
        row = await self._repo.get_allocation(allocation_id=allocation_id)
        if row is None or row["farm_id"] != farm_id:
            raise AllocationNotFoundError(allocation_id)
        tree = await self.get_full_tree(template_id=row["template_id"])
        current = int(tree.get("revision") or 0)
        return {
            "allocation_id": allocation_id,
            "template_id": row["template_id"],
            "applied_revision": row["template_revision"],
            "current_revision": current,
            "manual_updated": current > row["template_revision"],
            **diff_snapshots(row.get("manual_snapshot"), snapshot_of(tree)),
        }

    async def publish_impact(self, *, template_id: UUID) -> dict[str, Any]:
        """For the Publish step (H6): what changed since the last publish and
        how many farms use the manual. Counts only, never which farms (H7)."""
        template = await self._repo.get_template(template_id=template_id)
        if template is None:
            raise PlanTemplateNotFoundError(template_id)
        tree = await self.get_full_tree(template_id=template_id)
        usage = await self._repo.count_template_usage(template_id=template_id)
        return {
            "template_id": template_id,
            "revision": template.revision or 0,
            "published_at": template.published_at,
            **usage,
            **diff_snapshots(template.published_snapshot, snapshot_of(tree)),
        }

    async def delete_allocation(
        self,
        *,
        farm_id: UUID,
        allocation_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
    ) -> None:
        """Soft-delete the saved plan and its still-scheduled activities (F4).
        Started, completed and skipped activities stay on the board."""
        row = await self._repo.get_allocation(allocation_id=allocation_id)
        if row is None or row["farm_id"] != farm_id:
            raise AllocationNotFoundError(allocation_id)
        removed = await self._repo.soft_delete_allocation_scheduled(
            allocation_id=allocation_id, actor_user_id=actor_user_id
        )
        await self._repo.soft_delete_allocation(
            allocation_id=allocation_id, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="plan_allocations.deleted",
            actor_user_id=actor_user_id,
            subject_kind="plan_allocation",
            subject_id=allocation_id,
            farm_id=farm_id,
            details={"scheduled_activities_removed": removed},
        )


def assign_activity_codes(activities: list[dict[str, Any]]) -> None:
    """Give every activity without a ``code`` one that is unused in the list:
    ``<activity_type>-<n>``, the same shape the 0104 backfill used."""
    taken = {str(a["code"]) for a in activities if a.get("code")}
    for a in activities:
        if a.get("code"):
            continue
        n = 1
        while f"{a['activity_type']}-{n}" in taken:
            n += 1
        a["code"] = f"{a['activity_type']}-{n}"
        taken.add(a["code"])


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
