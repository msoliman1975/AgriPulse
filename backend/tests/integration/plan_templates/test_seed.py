"""PR-E5: the seeded mango starter template (migration 0035) is usable.

Asserts the `mango-season-eg` demonstrator exists with all three anchor
kinds and that its stage-anchored activities resolve to concrete dates
against the seeded mango phenology. The template was archived by migration
0040 in favour of the per-cultivar mango templates, so it is no longer
``published`` — the resolve mechanics are still exercised here.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.apply import resolve_schedule
from app.modules.plan_templates.repository import PlanTemplatesRepository

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_seeded_mango_template_resolves(admin_session: AsyncSession) -> None:
    template_id = (
        await admin_session.execute(
            text("SELECT id FROM public.plan_templates WHERE code = 'mango-season-eg'")
        )
    ).scalar_one()
    status = (
        await admin_session.execute(
            text("SELECT status FROM public.plan_templates WHERE id = :id"), {"id": template_id}
        )
    ).scalar_one()
    # Archived by 0040 in favour of the per-cultivar mango templates.
    assert status == "archived"

    repo = PlanTemplatesRepository(public_session=admin_session)
    tree = await repo.get_full_tree(template_id=template_id)
    assert tree is not None
    assert tree["crop_path"] == "mango"
    assert len(tree["milestones"]) == 1
    anchors = sorted(a["anchor"] for a in tree["activities"])
    # one start, one milestone, three stage-anchored.
    assert anchors == ["milestone", "stage", "stage", "stage", "start"]

    is_perennial, stages = await repo.resolve_phenology_for_path(crop_path="mango")
    assert is_perennial is True
    resolved, skipped = resolve_schedule(
        activities=tree["activities"],
        milestones=tree["milestones"],
        stages=stages,
        block_start_date=date(2026, 1, 1),
        planting_date=date(2018, 6, 1),
        is_perennial=True,
        season_year=2026,
    )
    # Every activity resolves; nothing skipped (all stages exist in mango).
    assert skipped == []
    assert len(resolved) == 5
    by_stage = {a.anchored_stage_code: a.scheduled_date for a in resolved if a.anchored_stage_code}
    # post_harvest_flush starts 07-16 (+7d) -> 2026-07-23.
    assert by_stage["post_harvest_flush"] == date(2026, 7, 23)
    # fruit_development starts 05-01 (+0) -> 2026-05-01.
    assert by_stage["fruit_development"] == date(2026, 5, 1)
