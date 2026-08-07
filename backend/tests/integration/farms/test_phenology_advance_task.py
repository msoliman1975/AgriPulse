"""Integration test: phenology auto-advance task (PR-C1).

Seeds a mango block (crop-level stages cover all 12 months via 0033),
runs the per-tenant task, and asserts the block lands on the resolver's
stage with a source='derived' log — plus lock + idempotency behaviour.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.phenology_advance import stage_for_date
from app.modules.farms.phenology_tasks import _advance_for_tenant_async
from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


async def _schema_for(admin_session: AsyncSession, tenant_id) -> str:
    return (
        await admin_session.execute(
            text("SELECT schema_name FROM public.tenants WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": tenant_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_auto_advance_sets_derived_stage_and_respects_lock(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pheno-adv", name="Pheno Adv", contact_email="ops@pheno-adv.test"
    )
    schema = await _schema_for(admin_session, tenant.tenant_id)

    crop_id = (
        await admin_session.execute(text("SELECT id FROM public.crops WHERE code='mango'"))
    ).scalar_one()
    variety_id = (
        await admin_session.execute(
            text("SELECT id FROM public.crop_varieties WHERE path='mango.alphonso'")
        )
    ).scalar_one()
    strain_id = (
        await admin_session.execute(
            text("SELECT id FROM public.crop_variety_strains WHERE path='mango.alphonso.short'")
        )
    ).scalar_one()
    mango_stages = (
        await admin_session.execute(
            text("SELECT phenology_stages FROM public.crops WHERE code='mango'")
        )
    ).scalar_one()

    today = date.today()
    expected = stage_for_date(
        mango_stages["stages"], is_perennial=True, planting_date=date(2020, 6, 1), today=today
    )
    assert expected is not None  # mango windows cover all 12 months

    # Insert farm + block + current block_crop directly in the tenant schema.
    farm_id, block_id, bc_id = uuid4(), uuid4(), uuid4()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, 'PA', 'PA Farm', "
            " ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0)))'), "
            " 'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": farm_id},
    )
    await admin_session.execute(
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
    await admin_session.execute(
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
            "id": bc_id,
            "block": block_id,
            "crop": crop_id,
            "variety": variety_id,
            "strain": strain_id,
        },
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    # First run: advances to the derived stage.
    res = await _advance_for_tenant_async(schema)
    assert res["advanced"] == 1, res

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    stage = (
        await admin_session.execute(
            text("SELECT growth_stage FROM block_crops WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": bc_id},
        )
    ).scalar_one()
    assert stage == expected
    derived = (
        await admin_session.execute(
            text(
                "SELECT count(*) FROM growth_stage_logs "
                "WHERE block_crop_id = :id AND source = 'derived'"
            ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": bc_id},
        )
    ).scalar_one()
    assert derived == 1
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    # Second run: idempotent (already on the computed stage -> no advance).
    res2 = await _advance_for_tenant_async(schema)
    assert res2["advanced"] == 0, res2

    # Lock + drift the stage: a locked block is never auto-advanced.
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "UPDATE block_crops SET growth_stage = 'veg_flush', growth_stage_locked = TRUE "
            "WHERE id = :id"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": bc_id},
    )
    await admin_session.execute(text("SET search_path TO public"))
    await admin_session.commit()

    res3 = await _advance_for_tenant_async(schema)
    assert res3["advanced"] == 0, res3
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    locked_stage = (
        await admin_session.execute(
            text("SELECT growth_stage FROM block_crops WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": bc_id},
        )
    ).scalar_one()
    assert locked_stage == "veg_flush"  # untouched
    await admin_session.execute(text("SET search_path TO public"))
