"""Repeating manual tasks (public 0115) against a real database: the seeded
Medjool 1.7 values, the CHECK, and the authoring round-trip."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.schemas import PlanTemplateActivityInput
from app.modules.plan_templates.service import get_plan_templates_service
from tests.integration.plan_templates.test_authoring import _write

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_medjool_1_7_tasks_carry_their_repeat(admin_session: AsyncSession) -> None:
    rows = (
        await admin_session.execute(
            text(
                """
                SELECT t.code AS template, a.code, a.repeat_count, a.repeat_unit
                  FROM public.plan_template_activities a
                  JOIN public.plan_templates t ON t.id = a.template_id
                 WHERE t.code LIKE 'medjool-organic-%-1-7'
                """
            )
        )
    ).all()
    by_key = {(r.template, r.code): (r.repeat_count, r.repeat_unit) for r in rows}
    assert by_key[("medjool-organic-bearing-eg-1-7", "irrigation-6")] == (2, "week")
    assert by_key[("medjool-organic-bearing-eg-1-7", "trap_service-1")] == (2, "month")
    assert by_key[("medjool-organic-bearing-eg-1-7", "harvesting-1")] == (2, "season")
    assert by_key[("medjool-organic-new-planting-eg-1-7", "irrigation-4")] == (2, "week")
    # Tasks done once stay single.
    assert by_key[("medjool-organic-bearing-eg-1-7", "spraying-1")] == (None, None)
    assert sum(1 for v in by_key.values() if v[0] is not None) == 22


@pytest.mark.asyncio
async def test_check_refuses_half_a_repeat(admin_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            text(
                "UPDATE public.plan_template_activities SET repeat_count = 2 "
                "WHERE id = (SELECT id FROM public.plan_template_activities "
                "            WHERE repeat_count IS NULL LIMIT 1)"
            )
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_authoring_keeps_the_repeat(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)
    payload = _write(
        "mango-repeat-1",
        activities=[
            PlanTemplateActivityInput(
                activity_type="irrigation",
                anchor="start",
                duration_days=28,
                repeat_count=2,
                repeat_unit="week",
            ),
            PlanTemplateActivityInput(activity_type="soil_prep", anchor="start"),
        ],
    )
    created = await svc.create_template(payload=payload, actor_user_id=None)
    tree = await svc.get_full_tree(template_id=created["id"])
    got = {a["activity_type"]: (a["repeat_count"], a["repeat_unit"]) for a in tree["activities"]}
    assert got == {"irrigation": (2, "week"), "soil_prep": (None, None)}
    await admin_session.rollback()
