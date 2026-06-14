"""PR-E1: plan-template catalog schema + repo reads + CHECK constraints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.repository import PlanTemplatesRepository

pytestmark = [pytest.mark.integration]


async def _seed_template(session: AsyncSession) -> tuple:
    tid, mid = uuid4(), uuid4()
    code = f"mango-std-{tid.hex[:6]}"
    await session.execute(
        text(
            "INSERT INTO public.plan_templates (id, code, name, crop_path, status) "
            "VALUES (:id, :code, 'Mango standard', 'mango', 'published')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": tid, "code": code},
    )
    await session.execute(
        text(
            "INSERT INTO public.plan_template_milestones "
            "(id, template_id, code, name, day_from_start, sort_order) "
            "VALUES (:id, :tid, 'bloom', 'Bloom', 60, 1)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": mid, "tid": tid},
    )
    # start + milestone + stage anchored activities
    await session.execute(
        text(
            "INSERT INTO public.plan_template_activities "
            "(template_id, activity_type, anchor, offset_days, duration_days, sort_order) "
            "VALUES (:tid, 'soil_prep', 'start', 0, 1, 1)"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tid},
    )
    await session.execute(
        text(
            "INSERT INTO public.plan_template_activities "
            "(template_id, activity_type, anchor, milestone_id, offset_days, sort_order) "
            "VALUES (:tid, 'spraying', 'milestone', :mid, -3, 2)"
        ).bindparams(
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
        ),
        {"tid": tid, "mid": mid},
    )
    await session.execute(
        text(
            "INSERT INTO public.plan_template_activities "
            "(template_id, activity_type, anchor, stage_code, offset_days, sort_order) "
            "VALUES (:tid, 'fertilizing', 'stage', 'post_harvest_flush', 7, 3)"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tid},
    )
    await session.commit()
    return tid, code


@pytest.mark.asyncio
async def test_full_tree_round_trip(admin_session: AsyncSession) -> None:
    tid, code = await _seed_template(admin_session)
    repo = PlanTemplatesRepository(public_session=admin_session)

    listing = await repo.list_templates(status_filter=("published",))
    assert any(t["code"] == code for t in listing)

    tree = await repo.get_full_tree(template_id=tid)
    assert tree is not None
    assert tree["crop_path"] == "mango"
    assert len(tree["milestones"]) == 1
    anchors = {a["anchor"] for a in tree["activities"]}
    assert anchors == {"start", "milestone", "stage"}
    stage_act = next(a for a in tree["activities"] if a["anchor"] == "stage")
    assert stage_act["stage_code"] == "post_harvest_flush"
    assert stage_act["offset_days"] == 7


@pytest.mark.asyncio
async def test_stage_anchor_requires_stage_code(admin_session: AsyncSession) -> None:
    tid = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.plan_templates (id, code, name, crop_path) "
            "VALUES (:id, :code, 'X', 'mango')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": tid, "code": f"x-{tid.hex[:6]}"},
    )
    await admin_session.commit()
    # anchor='stage' without stage_code violates the CHECK constraint.
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            text(
                "INSERT INTO public.plan_template_activities "
                "(template_id, activity_type, anchor) VALUES (:tid, 'fertilizing', 'stage')"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"tid": tid},
        )
    await admin_session.rollback()
