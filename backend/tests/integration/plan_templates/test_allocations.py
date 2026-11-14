"""Agri Operation PR 3: saved plans (allocations) end to end, service level.

Uses the seeded mango-alphonso-eg manual on a mango.alphonso.short block.
Covers: preview with exclusions / edits / a custom activity / a date
override; save + apply; a board reschedule kept in the saved plan (C4);
re-apply keeping completed rows (no duplicates); two saved plans in one
season (B2); a non-matching block refused (C3); delete removing only
still-scheduled rows, by soft delete (F4).
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.errors import AllocationBlocksRejectedError
from app.modules.plan_templates.schemas import AllocationWriteRequest
from app.modules.plan_templates.service import get_plan_templates_service
from app.modules.plans.service import get_plans_service
from app.modules.tenancy.service import get_tenant_service
from tests.integration.plan_templates.test_apply import _seed_block

pytestmark = [pytest.mark.integration]

START = date(2026, 3, 1)


async def _tenant_schema(session: AsyncSession, slug: str) -> str:
    tenant = await get_tenant_service(session).create_tenant(
        slug=slug, name=slug, contact_email=f"ops@{slug}.test"
    )
    return str(
        (
            await session.execute(
                text("SELECT schema_name FROM public.tenants WHERE id = :id").bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True))
                ),
                {"id": tenant.tenant_id},
            )
        ).scalar_one()
    )


async def _template_id(session: AsyncSession, code: str):  # type: ignore[no-untyped-def]
    return (
        await session.execute(
            text("SELECT id FROM public.plan_templates WHERE code = :c"), {"c": code}
        )
    ).scalar_one()


async def _rows(session: AsyncSession, schema: str, allocation_id) -> list:  # type: ignore[no-untyped-def]
    await session.execute(text(f"SET search_path TO {schema}, public"))
    rows = (
        await session.execute(
            text(
                "SELECT id, activity_key, scheduled_date, status, date_overridden, "
                "       product_name, title, source, deleted_at "
                "FROM plan_activities WHERE allocation_id = :a ORDER BY activity_key, created_at"
            ).bindparams(bindparam("a", type_=PG_UUID(as_uuid=True))),
            {"a": allocation_id},
        )
    ).all()
    return list(rows)


def _payload(template_id, block_id, custom_key: str) -> AllocationWriteRequest:  # type: ignore[no-untyped-def]
    return AllocationWriteRequest(
        template_id=template_id,
        season_label="Main season 2026",
        season_year=2026,
        blocks=[{"block_id": block_id, "start_date": START}],
        excluded_codes=["thinning-1"],
        activity_edits={"fertilizing-1": {"product_name": "Farm urea"}},
        custom_activities=[
            {
                "key": custom_key,
                "activity_type": "observation",
                "title": "Walk the rows",
                "week": 3,
            }
        ],
        date_overrides={block_id: {"pruning-1": date(2026, 10, 1)}},
    )


async def _preview_and_save(svc, schema, farm_id, payload, custom_key):  # type: ignore[no-untyped-def]
    preview = await svc.preview_allocation(farm_id=farm_id, payload=payload)
    assert preview["rejected_blocks"] == []
    assert preview["missing_codes"] == []
    acts = {a["activity_key"]: a for a in preview["blocks"][0]["activities"]}
    assert "thinning-1" not in acts
    assert len(acts) == 16  # 16 manual - 1 excluded + 1 custom
    assert acts["fertilizing-1"]["product_name"] == "Farm urea"
    assert acts[custom_key]["scheduled_date"] == START + timedelta(days=14)
    assert acts["pruning-1"]["scheduled_date"] == date(2026, 10, 1)
    assert acts["pruning-1"]["date_overridden"] is True

    saved = await svc.save_allocation(
        farm_id=farm_id,
        allocation_id=None,
        payload=payload,
        actor_user_id=None,
        tenant_schema=schema,
    )
    assert saved["activities_created"] == 16
    assert saved["allocation"]["template_code"] == "mango-alphonso-eg"
    assert saved["allocation"]["manual_updated"] is False
    return saved["allocation"]["id"]


async def _complete_and_move(session, schema, allocation_id):  # type: ignore[no-untyped-def]
    """Complete soil_prep-1 and move observation-1 on the Plan board."""
    live = [r for r in await _rows(session, schema, allocation_id) if r.deleted_at is None]
    assert len(live) == 16
    assert all(r.title for r in live)
    assert {r.source for r in live} == {"template", "custom"}
    done = next(r for r in live if r.activity_key == "soil_prep-1")
    moved = next(r for r in live if r.activity_key == "observation-1")
    new_date = moved.scheduled_date + timedelta(days=5)
    plans = get_plans_service(tenant_session=session)
    await plans.update_activity(
        activity_id=done.id,
        metadata_changes={},
        state_action="complete",
        actor_user_id=None,
        tenant_schema=schema,
    )
    await plans.update_activity(
        activity_id=moved.id,
        metadata_changes={"scheduled_date": new_date},
        state_action=None,
        actor_user_id=None,
        tenant_schema=schema,
    )
    await session.commit()
    return new_date


async def _reapply_as_read(svc, session, schema, farm_id, allocation_id, block_id, new_date):  # type: ignore[no-untyped-def]
    await session.execute(text(f"SET search_path TO {schema}, public"))
    view = await svc.get_allocation(farm_id=farm_id, allocation_id=allocation_id)
    assert view["date_overrides"][str(block_id)]["observation-1"] == new_date.isoformat()
    again = await svc.save_allocation(
        farm_id=farm_id,
        allocation_id=allocation_id,
        payload=AllocationWriteRequest(
            template_id=view["template_id"],
            season_label=view["season_label"],
            season_year=view["season_year"],
            blocks=view["blocks"],
            excluded_codes=view["excluded_codes"],
            activity_edits=view["activity_edits"],
            custom_activities=view["custom_activities"],
            date_overrides=view["date_overrides"],
        ),
        actor_user_id=None,
        tenant_schema=schema,
    )
    await session.commit()
    assert again["activities_kept"] == 1  # the completed one is not recreated
    assert again["activities_created"] == 15
    rows = await _rows(session, schema, allocation_id)
    live = [r for r in rows if r.deleted_at is None]
    assert len(live) == 16
    assert sum(1 for r in live if r.activity_key == "soil_prep-1") == 1
    obs = next(r for r in live if r.activity_key == "observation-1")
    assert obs.scheduled_date == new_date
    assert obs.date_overridden is True
    # Replaced rows are soft-deleted, never hard-deleted.
    assert any(r.deleted_at is not None for r in rows)
    return view["plan_id"]


async def _second_plan_then_delete_first(  # type: ignore[no-untyped-def]
    svc, session, schema, farm_id, template_id, block_id, allocation_id, plan_id
):
    codes = [a["code"] for a in (await svc.get_full_tree(template_id=template_id))["activities"]]
    await session.execute(text(f"SET search_path TO {schema}, public"))
    second = await svc.save_allocation(
        farm_id=farm_id,
        allocation_id=None,
        payload=AllocationWriteRequest(
            template_id=template_id,
            season_label="Main season 2026",
            season_year=2026,
            blocks=[{"block_id": block_id, "start_date": START}],
            excluded_codes=[c for c in codes if c != "harvesting-1"],
        ),
        actor_user_id=None,
        tenant_schema=schema,
    )
    await session.commit()
    assert second["activities_created"] == 1
    assert second["allocation"]["plan_id"] == plan_id  # same season, same plan (B2)
    await session.execute(text(f"SET search_path TO {schema}, public"))
    assert len(await svc.list_allocations(farm_id=farm_id)) == 2

    await svc.delete_allocation(
        farm_id=farm_id, allocation_id=allocation_id, actor_user_id=None, tenant_schema=schema
    )
    await session.commit()
    live = [r for r in await _rows(session, schema, allocation_id) if r.deleted_at is None]
    assert [r.activity_key for r in live] == ["soil_prep-1"]
    assert live[0].status == "completed"
    second_rows = await _rows(session, schema, second["allocation"]["id"])
    assert len([r for r in second_rows if r.deleted_at is None]) == 1
    await session.execute(text(f"SET search_path TO {schema}, public"))
    assert len(await svc.list_allocations(farm_id=farm_id)) == 1


@pytest.mark.asyncio
async def test_saved_plan_lifecycle(admin_session: AsyncSession) -> None:
    schema = await _tenant_schema(admin_session, "pt-alloc")
    farm_id, block_id = await _seed_block(admin_session, schema)
    template_id = await _template_id(admin_session, "mango-alphonso-eg")
    custom_key = f"custom:{uuid4().hex[:12]}"

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    svc = get_plan_templates_service(public_session=admin_session, tenant_session=admin_session)
    allocation_id = await _preview_and_save(
        svc, schema, farm_id, _payload(template_id, block_id, custom_key), custom_key
    )
    await admin_session.commit()
    new_date = await _complete_and_move(admin_session, schema, allocation_id)
    plan_id = await _reapply_as_read(
        svc, admin_session, schema, farm_id, allocation_id, block_id, new_date
    )
    await _second_plan_then_delete_first(
        svc, admin_session, schema, farm_id, template_id, block_id, allocation_id, plan_id
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()


@pytest.mark.asyncio
async def test_non_matching_block_is_refused(admin_session: AsyncSession) -> None:
    schema = await _tenant_schema(admin_session, "pt-alloc-gate")
    farm_id, block_id = await _seed_block(admin_session, schema)
    keitt = await _template_id(admin_session, "mango-keitt-eg")  # block is Alphonso
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    svc = get_plan_templates_service(public_session=admin_session, tenant_session=admin_session)
    payload = AllocationWriteRequest(
        template_id=keitt,
        season_label="2026",
        season_year=2026,
        blocks=[{"block_id": block_id, "start_date": START}],
    )
    preview = await svc.preview_allocation(farm_id=farm_id, payload=payload)
    assert preview["blocks"] == []
    assert preview["rejected_blocks"][0]["reason"] == "block_crop_does_not_match_manual"
    with pytest.raises(AllocationBlocksRejectedError):
        await svc.save_allocation(
            farm_id=farm_id,
            allocation_id=None,
            payload=payload,
            actor_user_id=None,
            tenant_schema=schema,
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_manual_updates_reach_the_publish_step_and_the_farm(
    admin_session: AsyncSession,
) -> None:
    from app.modules.plan_templates.schemas import (
        PlanTemplateActivityInput,
        PlanTemplateWriteRequest,
    )

    def manual(acts: list[PlanTemplateActivityInput]) -> PlanTemplateWriteRequest:
        return PlanTemplateWriteRequest(
            code="mango-revisions", name="Mango revisions", crop_path="mango", activities=acts
        )

    schema = await _tenant_schema(admin_session, "pt-alloc-rev")
    farm_id, block_id = await _seed_block(admin_session, schema)
    svc = get_plan_templates_service(public_session=admin_session, tenant_session=admin_session)
    v1 = [
        PlanTemplateActivityInput(code="pruning-1", activity_type="pruning", anchor="start"),
        PlanTemplateActivityInput(
            code="fertilizing-1", activity_type="fertilizing", anchor="start", offset_days=7
        ),
    ]
    created = await svc.create_template(payload=manual(v1), actor_user_id=None)
    template_id = created["id"]
    # Never published: nothing to compare against.
    impact = await svc.publish_impact(template_id=template_id)
    assert impact["comparable"] is False
    await svc.set_status(template_id=template_id, status="published", actor_user_id=None)
    await admin_session.commit()

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    saved = await svc.save_allocation(
        farm_id=farm_id,
        allocation_id=None,
        payload=AllocationWriteRequest(
            template_id=template_id,
            season_label="2026",
            season_year=2026,
            blocks=[{"block_id": block_id, "start_date": START}],
        ),
        actor_user_id=None,
        tenant_schema=schema,
    )
    await admin_session.commit()
    allocation_id = saved["allocation"]["id"]

    # The platform edits the draft: changes one, drops one, adds one.
    await svc.update_template(
        template_id=template_id,
        payload=manual(
            [
                PlanTemplateActivityInput(
                    code="fertilizing-1",
                    activity_type="fertilizing",
                    anchor="start",
                    offset_days=14,
                ),
                PlanTemplateActivityInput(activity_type="spraying", anchor="start"),
            ]
        ),
        actor_user_id=None,
    )
    await admin_session.commit()
    impact = await svc.publish_impact(template_id=template_id)
    assert impact["comparable"] is True
    assert impact["farms"] == 1
    assert impact["saved_plans"] == 1
    assert [a["code"] for a in impact["added"]] == ["spraying-1"]
    assert [r["code"] for r in impact["removed"]] == ["pruning-1"]
    assert impact["changed"][0]["fields"] == ["offset_days"]

    # Until it is published again the farm sees no update.
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    before = await svc.manual_changes(farm_id=farm_id, allocation_id=allocation_id)
    assert before["manual_updated"] is False
    await svc.set_status(template_id=template_id, status="published", actor_user_id=None)
    await admin_session.commit()

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    after = await svc.manual_changes(farm_id=farm_id, allocation_id=allocation_id)
    assert after["manual_updated"] is True
    assert after["applied_revision"] == 1
    assert after["current_revision"] == 2
    assert [a["code"] for a in after["added"]] == ["spraying-1"]
    assert [r["code"] for r in after["removed"]] == ["pruning-1"]
    view = await svc.get_allocation(farm_id=farm_id, allocation_id=allocation_id)
    assert view["manual_updated"] is True
    # Publish leaves nothing pending.
    assert (await svc.publish_impact(template_id=template_id))["changed"] == []
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()
