"""F1 (Agri Operation): a recommendation a saved plan already covers.

When the engine opens a recommendation, the INSERT looks for a live activity on
the same block whose manual activity names the tree (``source_tree_code``),
still scheduled or in progress, within 14 days of today, and stores it in
``recommendations.plan_activity_id``. The Action Center returns it as the
planned activity. Only a real database can prove the lookup and the join.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.modules.action_center.repository import ActionCenterRepository
from app.modules.action_center.service import to_item
from app.modules.recommendations.repository import RecommendationsRepository
from app.modules.tenancy.service import get_tenant_service
from app.shared import clock

pytestmark = [pytest.mark.integration]

_POLY = "POLYGON((31.2 30.0,31.3 30.0,31.3 30.1,31.2 30.1,31.2 30.0))"
_TREE = "t_hopper_f1"
_TODAY = date(2026, 3, 10)
_SHARED: dict[str, Any] = {}


async def _use_tenant(session: Any) -> None:
    """A commit hands the connection back to the pool, so the search path is
    set again before each step."""
    await session.execute(text(f'SET search_path TO "{_SHARED["schema"]}", public'))


async def _seed(session: Any) -> dict[str, Any]:
    """A farm with two blocks, a plan, and a manual whose spraying activity
    names the tree. Built once for the module (a tenant replays every
    migration)."""
    if _SHARED:
        await _use_tenant(session)
        return _SHARED
    slug = f"f1-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    await session.commit()
    _SHARED["schema"] = str(tenant.schema_name)
    await _use_tenant(session)

    farm_id = (
        await session.execute(
            text(
                """
                INSERT INTO farms (code, name, country_code, boundary, boundary_utm,
                                   centroid, area_m2)
                VALUES ('F1-FARM', 'F1 farm', 'EG', ST_GeomFromText(:p, 4326),
                        ST_Transform(ST_GeomFromText(:p, 4326), 32636),
                        ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326), 100000)
                RETURNING id
                """
            ),
            {"p": _POLY},
        )
    ).scalar_one()
    blocks = []
    for code in ("F1-A", "F1-B"):
        blocks.append(
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO blocks (farm_id, code, boundary, boundary_utm,
                                            centroid, area_m2, aoi_hash)
                        VALUES (:f, :c, ST_GeomFromText(:p, 4326),
                                ST_Transform(ST_GeomFromText(:p, 4326), 32636),
                                ST_SetSRID(ST_MakePoint(31.25, 30.05), 4326),
                                100000, :c)
                        RETURNING id
                        """
                    ),
                    {"f": farm_id, "c": code, "p": _POLY},
                )
            ).scalar_one()
        )
    plan_id = (
        await session.execute(
            text(
                "INSERT INTO vegetation_plans (farm_id, season_label, season_year) "
                "VALUES (:f, '2026', 2026) RETURNING id"
            ),
            {"f": farm_id},
        )
    ).scalar_one()

    template_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.plan_templates (id, code, name, crop_path, status) "
            "VALUES (:id, :code, 'F1 manual', 'mango', 'published')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": template_id, "code": f"f1-{template_id.hex[:6]}"},
    )
    spray_activity = (
        await session.execute(
            text(
                "INSERT INTO public.plan_template_activities "
                "(template_id, code, activity_type, title, anchor, offset_days, "
                " sort_order, source_tree_code) "
                "VALUES (:t, 'spraying-1', 'spraying', 'Spray against hopper', 'start', "
                " 0, 1, :tree) RETURNING id"
            ).bindparams(bindparam("t", type_=PG_UUID(as_uuid=True))),
            {"t": template_id, "tree": _TREE},
        )
    ).scalar_one()
    await session.commit()
    _SHARED.update(
        farm_id=farm_id,
        blocks=blocks,
        plan_id=plan_id,
        spray_activity=spray_activity,
    )
    return _SHARED


async def _plan_activity(
    session: Any, seed: dict[str, Any], *, block: UUID, on: date, status: str = "scheduled"
) -> UUID:
    await _use_tenant(session)
    return (
        await session.execute(
            text(
                """
                INSERT INTO plan_activities (plan_id, farm_id, block_id, activity_type,
                                             scheduled_date, status,
                                             template_activity_id, title)
                VALUES (:plan, :farm, :block, 'spraying', :on, :status, :tpl,
                        'Spray against hopper')
                RETURNING id
                """
            ).bindparams(
                bindparam("plan", type_=PG_UUID(as_uuid=True)),
                bindparam("farm", type_=PG_UUID(as_uuid=True)),
                bindparam("block", type_=PG_UUID(as_uuid=True)),
                bindparam("tpl", type_=PG_UUID(as_uuid=True)),
            ),
            {
                "plan": seed["plan_id"],
                "farm": seed["farm_id"],
                "block": block,
                "on": on,
                "status": status,
                "tpl": seed["spray_activity"],
            },
        )
    ).scalar_one()


async def _open(session: Any, seed: dict[str, Any], *, block: UUID, tree_code: str = _TREE):
    await _use_tenant(session)
    rec_id = uuid4()
    repo = RecommendationsRepository(tenant_session=session, public_session=session)
    assert await repo.insert_recommendation(
        recommendation_id=rec_id,
        block_id=block,
        farm_id=seed["farm_id"],
        tree_id=uuid4(),
        tree_code=tree_code,
        tree_version=1,
        block_crop_id=None,
        action_type="spray",
        severity="warning",
        parameters={},
        actions={},
        confidence=Decimal("0.8"),
        tree_path=[{"node_id": "leaf"}],
        text_en="Spray for leafhopper",
        text_ar=None,
        valid_until=None,
        evaluation_snapshot={},
        actor_user_id=None,
        today=_TODAY,
    )
    await session.commit()
    return rec_id


async def _linked(session: Any, rec_id: UUID) -> UUID | None:
    await _use_tenant(session)
    return (
        await session.execute(
            text("SELECT plan_activity_id FROM recommendations WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": rec_id},
        )
    ).scalar_one()


async def _close(session: Any, *ids: UUID) -> None:
    """Free the (block, tree) open slot for the next case."""
    await _use_tenant(session)
    for rec_id in ids:
        await session.execute(
            text("UPDATE recommendations SET deleted_at = now() WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": rec_id},
        )
    await session.commit()


@pytest.mark.asyncio
async def test_links_the_nearest_live_planned_activity(admin_session: Any) -> None:
    seed = await _seed(admin_session)
    block_a, block_b = seed["blocks"]
    near = await _plan_activity(admin_session, seed, block=block_a, on=_TODAY + timedelta(days=3))
    await _plan_activity(admin_session, seed, block=block_a, on=_TODAY - timedelta(days=10))
    # Out of the window, another block, or already done: none of these count.
    await _plan_activity(admin_session, seed, block=block_a, on=_TODAY + timedelta(days=20))
    await _plan_activity(admin_session, seed, block=block_b, on=_TODAY)
    await admin_session.commit()

    rec = await _open(admin_session, seed, block=block_a)
    assert await _linked(admin_session, rec) == near

    await _use_tenant(admin_session)
    ac = ActionCenterRepository(tenant_session=admin_session)
    row = await ac.get_item(farm_id=seed["farm_id"], item_id=rec)
    assert row is not None
    item = to_item(row, now=clock.now())
    assert item.planned_activity_id == near
    assert item.planned_date == _TODAY + timedelta(days=3)
    assert item.planned_title == "Spray against hopper"
    await _close(admin_session, rec)


@pytest.mark.asyncio
async def test_no_link_without_a_matching_live_activity(admin_session: Any) -> None:
    seed = await _seed(admin_session)
    block_b = seed["blocks"][1]
    # block B has a scheduled one from the first test, today. A different tree
    # does not match it.
    other = await _open(admin_session, seed, block=block_b, tree_code="t_some_other_tree")
    assert await _linked(admin_session, other) is None
    await _close(admin_session, other)

    # Completed and deleted activities do not count either.
    await _use_tenant(admin_session)
    await admin_session.execute(
        text("UPDATE plan_activities SET status = 'completed' WHERE block_id = :b").bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True))
        ),
        {"b": block_b},
    )
    await admin_session.commit()
    done = await _open(admin_session, seed, block=block_b)
    assert await _linked(admin_session, done) is None
    await _close(admin_session, done)


@pytest.mark.asyncio
async def test_deleting_the_activity_unlinks_it_in_the_queue(admin_session: Any) -> None:
    seed = await _seed(admin_session)
    block_a = seed["blocks"][0]
    act = await _plan_activity(admin_session, seed, block=block_a, on=_TODAY)
    await admin_session.commit()
    rec = await _open(admin_session, seed, block=block_a)
    assert await _linked(admin_session, rec) == act

    await _use_tenant(admin_session)
    await admin_session.execute(
        text("UPDATE plan_activities SET deleted_at = now() WHERE id = :id").bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True))
        ),
        {"id": act},
    )
    await admin_session.commit()
    await _use_tenant(admin_session)
    row = await ActionCenterRepository(tenant_session=admin_session).get_item(
        farm_id=seed["farm_id"], item_id=rec
    )
    assert row is not None
    assert to_item(row, now=clock.now()).planned_activity_id is None
    await _close(admin_session, rec)
