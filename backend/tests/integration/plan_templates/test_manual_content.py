"""Agri Operation PR 1: manual content fields, stable codes, revisions.

* Migration 0104 backfills codes, titles, evidence tiers and source trees on
  the seeded manuals.
* A whole-tree save keeps activity and milestone ids for codes that survive
  (decision B3), so saved plans can keep pointing at them.
* Every publish is a new revision (B4, H6).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.schemas import (
    PlanTemplateActivityInput,
    PlanTemplateMilestoneInput,
    PlanTemplateWriteRequest,
)
from app.modules.plan_templates.service import get_plan_templates_service

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_seeded_manuals_are_backfilled(admin_session: AsyncSession) -> None:
    pbz = (
        await admin_session.execute(
            text(
                "SELECT a.code, a.title, a.title_ar, a.evidence_tier, a.source_tree_code "
                "FROM public.plan_template_activities a "
                "JOIN public.plan_templates t ON t.id = a.template_id "
                "WHERE t.code = 'mango-keitt-eg' AND a.sort_order = 5"
            )
        )
    ).one()
    assert pbz.code == "growth_regulator-1"
    assert pbz.title == "PBZ treatment for flowering induction"
    assert pbz.title_ar
    assert pbz.evidence_tier == "generic"
    assert pbz.source_tree_code == "t_flower_induction_readiness"

    fao = (
        await admin_session.execute(
            text(
                "SELECT a.evidence_tier FROM public.plan_template_activities a "
                "JOIN public.plan_templates t ON t.id = a.template_id "
                "WHERE t.code = 'mango-zebda-eg' AND a.sort_order = 2"
            )
        )
    ).scalar_one()
    assert fao == "eg_fao"

    # Every activity of a live seeded manual has a title; Medjool is manual-sourced.
    missing = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM public.plan_template_activities a "
                "JOIN public.plan_templates t ON t.id = a.template_id "
                "WHERE (t.code LIKE 'mango-%-eg' OR t.code LIKE 'potato-%-eg' "
                "       OR t.code LIKE 'medjool-organic-%') "
                "  AND t.code <> 'mango-season-eg' "
                "  AND (a.title IS NULL OR a.title_ar IS NULL)"
            )
        )
    ).scalar_one()
    assert missing == 0
    tiers = (
        await admin_session.execute(
            text(
                "SELECT DISTINCT a.evidence_tier FROM public.plan_template_activities a "
                "JOIN public.plan_templates t ON t.id = a.template_id "
                "WHERE t.code LIKE 'medjool-organic-%'"
            )
        )
    ).scalars()
    assert set(tiers) == {"manual"}

    revisions = (
        await admin_session.execute(
            text(
                "SELECT DISTINCT revision FROM public.plan_templates "
                "WHERE code IN ('mango-keitt-eg', 'potato-nili-eg', "
                "               'medjool-organic-bearing-eg')"
            )
        )
    ).scalars()
    assert set(revisions) == {1}


def _payload(code: str, activities: list[PlanTemplateActivityInput]) -> PlanTemplateWriteRequest:
    return PlanTemplateWriteRequest(
        code=code,
        name="Mango codes",
        crop_path="mango",
        milestones=[
            PlanTemplateMilestoneInput(code="bud_break", name="Bud break", day_from_start=30)
        ],
        activities=activities,
    )


@pytest.mark.asyncio
async def test_save_keeps_ids_by_code(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)
    created = await svc.create_template(
        payload=_payload(
            "mango-codes-1",
            [
                PlanTemplateActivityInput(
                    activity_type="soil_prep",
                    anchor="start",
                    title="Land prep",
                    title_ar="تجهيز الأرض",
                ),
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
                    evidence_tier="eg_fao",
                ),
            ],
        ),
        actor_user_id=None,
    )
    await admin_session.commit()
    by_code = {a["code"]: a for a in created["activities"]}
    assert set(by_code) == {"soil_prep-1", "fertilizing-1", "fertilizing-2"}
    milestone_id = created["milestones"][0]["id"]

    # Edit: change soil_prep's title and offset, drop fertilizing-1, add a new one.
    updated = await svc.update_template(
        template_id=created["id"],
        payload=_payload(
            "mango-codes-1",
            [
                PlanTemplateActivityInput(
                    code="soil_prep-1",
                    activity_type="soil_prep",
                    anchor="start",
                    offset_days=3,
                    title="Land prep and basins",
                    title_ar="تجهيز الأرض والأحواض",
                ),
                PlanTemplateActivityInput(
                    code="fertilizing-2",
                    activity_type="fertilizing",
                    anchor="stage",
                    stage_code="post_harvest_flush",
                    offset_days=7,
                    evidence_tier="eg_fao",
                ),
                PlanTemplateActivityInput(
                    activity_type="pruning",
                    anchor="milestone",
                    milestone_code="bud_break",
                ),
            ],
        ),
        actor_user_id=None,
    )
    await admin_session.commit()
    after = {a["code"]: a for a in updated["activities"]}
    assert set(after) == {"soil_prep-1", "fertilizing-2", "pruning-1"}
    assert after["soil_prep-1"]["id"] == by_code["soil_prep-1"]["id"]
    assert after["soil_prep-1"]["offset_days"] == 3
    assert after["soil_prep-1"]["title"] == "Land prep and basins"
    assert after["fertilizing-2"]["id"] == by_code["fertilizing-2"]["id"]
    assert after["fertilizing-2"]["evidence_tier"] == "eg_fao"
    assert after["pruning-1"]["milestone_id"] == milestone_id
    assert updated["milestones"][0]["id"] == milestone_id


@pytest.mark.asyncio
async def test_duplicate_activity_codes_are_rejected(admin_session: AsyncSession) -> None:
    from app.modules.plan_templates.errors import PlanTemplateValidationError

    svc = get_plan_templates_service(public_session=admin_session)
    with pytest.raises(PlanTemplateValidationError):
        await svc.create_template(
            payload=_payload(
                "mango-codes-dup",
                [
                    PlanTemplateActivityInput(code="x-1", activity_type="pruning", anchor="start"),
                    PlanTemplateActivityInput(code="x-1", activity_type="pruning", anchor="start"),
                ],
            ),
            actor_user_id=None,
        )
    await admin_session.rollback()


@pytest.mark.asyncio
async def test_each_publish_is_a_new_revision(admin_session: AsyncSession) -> None:
    svc = get_plan_templates_service(public_session=admin_session)
    created = await svc.create_template(
        payload=_payload(
            "mango-codes-rev",
            [PlanTemplateActivityInput(activity_type="pruning", anchor="start")],
        ),
        actor_user_id=None,
    )
    await admin_session.commit()
    assert created["revision"] == 0
    first = await svc.set_status(template_id=created["id"], status="published", actor_user_id=None)
    await admin_session.commit()
    assert first["revision"] == 1
    assert first["published_at"] is not None
    second = await svc.set_status(template_id=created["id"], status="published", actor_user_id=None)
    await admin_session.commit()
    assert second["revision"] == 2
    archived = await svc.set_status(
        template_id=created["id"], status="archived", actor_user_id=None
    )
    await admin_session.commit()
    assert archived["revision"] == 2


@pytest.mark.asyncio
async def test_seeded_manuals_have_arabic_text(admin_session: AsyncSession) -> None:
    """1b (E3): every live seeded activity with English notes, product or
    dosage also has Arabic, and no evidence tag leaks into the Arabic."""
    gaps = (
        await admin_session.execute(
            text(
                "SELECT t.code, a.sort_order, "
                "  (a.notes IS NOT NULL AND a.notes_ar IS NULL) AS no_notes, "
                "  (a.product_name IS NOT NULL AND a.product_name_ar IS NULL) AS no_product, "
                "  (a.dosage IS NOT NULL AND a.dosage_ar IS NULL) AS no_dosage "
                "FROM public.plan_template_activities a "
                "JOIN public.plan_templates t ON t.id = a.template_id "
                "WHERE (t.code LIKE 'mango-%-eg' OR t.code LIKE 'potato-%-eg' "
                "       OR t.code LIKE 'medjool-organic-%') "
                "  AND t.code <> 'mango-season-eg' AND t.deleted_at IS NULL"
            )
        )
    ).all()
    missing = [g for g in gaps if g.no_notes or g.no_product or g.no_dosage]
    assert missing == []
    # Mango (6 x 16), potato (3 x 12), Medjool 1.3 (31 + 20) and the Medjool
    # 1.7 drafts from public 0111 (43 + 21), which the same Arabic check covers.
    assert len(gaps) == 6 * 16 + 3 * 12 + 31 + 20 + 43 + 21

    leaked = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM public.plan_template_activities "
                "WHERE notes_ar ~ '\\[(EG|GENERIC)'"
            )
        )
    ).scalar_one()
    assert leaked == 0

    pbz = (
        await admin_session.execute(
            text(
                "SELECT a.product_name_ar FROM public.plan_template_activities a "
                "JOIN public.plan_templates t ON t.id = a.template_id "
                "WHERE t.code = 'mango-zebda-eg' AND a.sort_order = 5"
            )
        )
    ).scalar_one()
    assert pbz == "باكلوبوترازول (PBZ)"
