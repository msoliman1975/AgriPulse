"""PR-E3: platform plan-template authoring (whole-tree CRUD + validation).

Exercises the service against the public catalog (admin_session): create a
mango stage-anchored template, the stage/milestone validation guards, the
whole-tree replace round-trip, publish, and soft-delete.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.errors import (
    PlanTemplateConflictError,
    PlanTemplateNotFoundError,
    PlanTemplateValidationError,
)
from app.modules.plan_templates.schemas import (
    PlanTemplateActivityInput,
    PlanTemplateMilestoneInput,
    PlanTemplateWriteRequest,
)
from app.modules.plan_templates.service import get_plan_templates_service

pytestmark = [pytest.mark.integration]


def _write(code: str, **over) -> PlanTemplateWriteRequest:
    base: dict = {
        "code": code,
        "name": "Mango season",
        "crop_path": "mango",
        "milestones": [
            PlanTemplateMilestoneInput(code="bud_break", name="Bud break", day_from_start=30),
        ],
        "activities": [
            PlanTemplateActivityInput(activity_type="soil_prep", anchor="start", offset_days=0),
            PlanTemplateActivityInput(
                activity_type="fertilizing",
                anchor="milestone",
                milestone_code="bud_break",
                offset_days=2,
            ),
            PlanTemplateActivityInput(
                activity_type="fertilizing",
                anchor="stage",
                stage_code="post_harvest_flush",
                offset_days=7,
            ),
        ],
    }
    base.update(over)
    return PlanTemplateWriteRequest(**base)


@pytest.mark.asyncio
async def test_create_replace_publish_delete(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)

    # Create the whole tree; resolves crop_id, draft by default.
    created = await svc.create_template(payload=_write("mango-auth-1"), actor_user_id=None)
    template_id = created["id"]
    assert created["status"] == "draft"
    assert len(created["milestones"]) == 1
    assert len(created["activities"]) == 3
    # crop_id denormalised from the path's first segment.
    assert created["crop_id"] is not None
    # milestone-anchored activity got its milestone_id resolved from the code.
    m_act = next(a for a in created["activities"] if a["anchor"] == "milestone")
    assert m_act["milestone_id"] == created["milestones"][0]["id"]
    stage_act = next(a for a in created["activities"] if a["anchor"] == "stage")
    assert stage_act["stage_code"] == "post_harvest_flush"
    await admin_session.commit()

    # Duplicate code -> conflict.
    with pytest.raises(PlanTemplateConflictError):
        await svc.create_template(payload=_write("mango-auth-1"), actor_user_id=None)

    # Whole-tree replace: drop the milestone activity, keep two.
    replacement = _write(
        "mango-auth-1",
        name="Mango season v2",
        milestones=[],
        activities=[
            PlanTemplateActivityInput(activity_type="soil_prep", anchor="start", offset_days=0),
            PlanTemplateActivityInput(
                activity_type="fertilizing",
                anchor="stage",
                stage_code="post_harvest_flush",
                offset_days=10,
            ),
        ],
    )
    updated = await svc.update_template(
        template_id=template_id, payload=replacement, actor_user_id=None
    )
    assert updated["name"] == "Mango season v2"
    assert updated["milestones"] == []
    assert len(updated["activities"]) == 2
    await admin_session.commit()

    # Publish.
    published = await svc.set_status(
        template_id=template_id, status="published", actor_user_id=None
    )
    assert published["status"] == "published"
    await admin_session.commit()

    # Soft-delete frees the row + the code.
    await svc.delete_template(template_id=template_id, actor_user_id=None)
    await admin_session.commit()
    with pytest.raises(PlanTemplateNotFoundError):
        await svc.get_full_tree(template_id=template_id)
    # Code is free again after retire.
    again = await svc.create_template(payload=_write("mango-auth-1"), actor_user_id=None)
    assert again["status"] == "draft"
    await admin_session.commit()


@pytest.mark.asyncio
async def test_validation_guards(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)

    # Unknown stage code for the crop path -> 422.
    bad_stage = _write(
        "mango-bad-stage",
        milestones=[],
        activities=[
            PlanTemplateActivityInput(
                activity_type="fertilizing", anchor="stage", stage_code="does_not_exist"
            )
        ],
    )
    with pytest.raises(PlanTemplateValidationError):
        await svc.create_template(payload=bad_stage, actor_user_id=None)

    # Milestone-anchored activity referencing a milestone that isn't defined.
    bad_ms = _write(
        "mango-bad-ms",
        milestones=[],
        activities=[
            PlanTemplateActivityInput(
                activity_type="fertilizing", anchor="milestone", milestone_code="ghost"
            )
        ],
    )
    with pytest.raises(PlanTemplateValidationError):
        await svc.create_template(payload=bad_ms, actor_user_id=None)
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_resolve_phenology_for_picker(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)
    resolved = await svc.resolve_phenology(crop_path="mango")
    assert resolved["is_perennial"] is True
    codes = {s["code"] for s in resolved["stages"]}
    assert "post_harvest_flush" in codes
