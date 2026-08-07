"""PR-E2: plan-template apply engine end-to-end (service level).

Seeds a published mango template (start + stage-anchored activities),
a mango block, and asserts preview + apply materialise plan_activities
with the right stage-resolved dates — and that re-apply is idempotent.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_templates.schemas import ApplyBlock
from app.modules.plan_templates.service import get_plan_templates_service
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


async def _seed_template(session: AsyncSession) -> tuple:
    tid = uuid4()
    code = f"mango-season-{tid.hex[:6]}"
    await session.execute(
        text(
            "INSERT INTO public.plan_templates (id, code, name, crop_path, status) "
            "VALUES (:id, :code, 'Mango season', 'mango', 'published')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": tid, "code": code},
    )
    # start-anchored land prep + stage-anchored post-harvest fertilization.
    await session.execute(
        text(
            "INSERT INTO public.plan_template_activities "
            "(template_id, activity_type, anchor, offset_days, sort_order) "
            "VALUES (:t, 'soil_prep', 'start', 0, 1)"
        ).bindparams(bindparam("t", type_=PG_UUID(as_uuid=True))),
        {"t": tid},
    )
    await session.execute(
        text(
            "INSERT INTO public.plan_template_activities "
            "(template_id, activity_type, anchor, stage_code, offset_days, sort_order) "
            "VALUES (:t, 'fertilizing', 'stage', 'post_harvest_flush', 7, 2)"
        ).bindparams(bindparam("t", type_=PG_UUID(as_uuid=True))),
        {"t": tid},
    )
    await session.commit()
    return tid, code


async def _seed_block(session: AsyncSession, schema: str) -> tuple:
    crop_id = (
        await session.execute(text("SELECT id FROM public.crops WHERE code='mango'"))
    ).scalar_one()
    variety_id = (
        await session.execute(
            text("SELECT id FROM public.crop_varieties WHERE path='mango.alphonso'")
        )
    ).scalar_one()
    strain_id = (
        await session.execute(
            text("SELECT id FROM public.crop_variety_strains WHERE path='mango.alphonso.short'")
        )
    ).scalar_one()
    farm_id, block_id = uuid4(), uuid4()
    await session.execute(text(f"SET search_path TO {schema}, public"))
    await session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, 'PT', 'PT Farm', "
            " ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0)))'), "
            " 'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": farm_id},
    )
    await session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, :farm, 'B1', "
            " ST_GeomFromEWKT('SRID=4326;POLYGON((31.2 30.0,31.201 30.0,31.201 30.001,31.2 30.001,31.2 30.0))'), "
            " 'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": block_id, "farm": farm_id},
    )
    await session.execute(
        text(
            "INSERT INTO block_crops (id, block_id, crop_id, crop_variety_id, "
            " crop_variety_strain_id, crop_path, season_label, planting_date, effective_from, "
            " is_current, status) "
            "VALUES (:id, :block, :crop, :variety, :strain, 'mango.alphonso.short', '2026', "
            # Open-ended from the planting date: a perennial assignment that
            # is still current, which is what the phenology sweep looks for.
            " '2020-06-01', '2020-06-01', TRUE, 'growing')"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("block", type_=PG_UUID(as_uuid=True)),
            bindparam("crop", type_=PG_UUID(as_uuid=True)),
            bindparam("variety", type_=PG_UUID(as_uuid=True)),
            bindparam("strain", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "id": uuid4(),
            "block": block_id,
            "crop": crop_id,
            "variety": variety_id,
            "strain": strain_id,
        },
    )
    await session.execute(text("SET search_path TO public"))
    await session.commit()
    return farm_id, block_id


@pytest.mark.asyncio
async def test_preview_and_apply_stage_anchored(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pt-apply", name="PT Apply", contact_email="ops@pt-apply.test"
    )
    schema = (
        await admin_session.execute(
            text("SELECT schema_name FROM public.tenants WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": tenant.tenant_id},
        )
    ).scalar_one()

    template_id, _ = await _seed_template(admin_session)
    farm_id, block_id = await _seed_block(admin_session, schema)

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    svc = get_plan_templates_service(public_session=admin_session, tenant_session=admin_session)
    blocks = [ApplyBlock(block_id=block_id, start_date=date(2026, 3, 1))]

    # Preview: 2 activities, stage-anchored one resolves to season-year DOY.
    preview = await svc.preview(
        template_id=template_id, farm_id=farm_id, season_year=2026, blocks=blocks
    )
    assert preview["total_activities"] == 2
    acts = preview["blocks"][0]["activities"]
    stage_act = next(a for a in acts if a["anchored_stage_code"] == "post_harvest_flush")
    # mango post_harvest_flush start_doy '07-16' (migration 0033) + 7 days.
    assert stage_act["scheduled_date"] == date(2026, 7, 23)

    # Apply: materialises plan + activities.
    res = await svc.apply(
        template_id=template_id,
        farm_id=farm_id,
        season_label="2026",
        season_year=2026,
        blocks=blocks,
        actor_user_id=None,
        tenant_schema=schema,
    )
    assert res["activities_created"] == 2
    assert res["blocks_applied"] == 1
    await admin_session.commit()

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    count = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM plan_activities "
                "WHERE applied_template_id = :t AND source = 'template'"
            ).bindparams(bindparam("t", type_=PG_UUID(as_uuid=True))),
            {"t": template_id},
        )
    ).scalar_one()
    assert count == 2
    stage_row = (
        await admin_session.execute(
            text(
                "SELECT anchored_stage_code FROM plan_activities "
                "WHERE applied_template_id = :t AND anchored_stage_code IS NOT NULL"
            ).bindparams(bindparam("t", type_=PG_UUID(as_uuid=True))),
            {"t": template_id},
        )
    ).scalar_one()
    assert stage_row == "post_harvest_flush"
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    # Re-apply is idempotent: still 2 template rows, not 4.
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    svc2 = get_plan_templates_service(public_session=admin_session, tenant_session=admin_session)
    res2 = await svc2.apply(
        template_id=template_id,
        farm_id=farm_id,
        season_label="2026",
        season_year=2026,
        blocks=blocks,
        actor_user_id=None,
        tenant_schema=schema,
    )
    await admin_session.commit()
    assert res2["activities_created"] == 2
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    recount = (
        await admin_session.execute(
            text("SELECT count(*) FROM plan_activities WHERE applied_template_id = :t").bindparams(
                bindparam("t", type_=PG_UUID(as_uuid=True))
            ),
            {"t": template_id},
        )
    ).scalar_one()
    assert recount == 2  # regenerated, not duplicated
    await admin_session.execute(text("SET search_path TO public"))
