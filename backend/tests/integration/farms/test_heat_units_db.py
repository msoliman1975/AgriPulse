"""Heat units configured per crop (D17) against the database.

Public 0113 (columns, CHECKs, the Medjool seed) and tenant 0109 (the block's
own start), then the loader the tree context builders call: the crop's base
from the catalogue, the method and start inherited down to Medjool, the start
read from the latest transition into the pollination stage, and the farm's
daily temperatures summed from it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.heat_units import load_heat_units_snapshot
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import PlatformRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]

_UUID = PG_UUID(as_uuid=True)


async def _schema_for(admin_session: AsyncSession, tenant_id) -> str:
    return (
        await admin_session.execute(
            text("SELECT schema_name FROM public.tenants WHERE id = :id").bindparams(
                bindparam("id", type_=_UUID)
            ),
            {"id": tenant_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_medjool_is_seeded_to_count_by_the_mean_from_pollination(
    admin_session: AsyncSession,
) -> None:
    base, upper = (
        await admin_session.execute(
            text(
                "SELECT gdd_base_temp_c, gdd_upper_temp_c FROM public.crops WHERE code='date_palm'"
            )
        )
    ).one()
    assert base == Decimal("18.0")
    assert upper == Decimal("38.0")
    row = (
        await admin_session.execute(
            text(
                "SELECT gdd_method, gdd_start_kind, gdd_start_value "
                "FROM public.crop_varieties WHERE path = 'date_palm.medjool'"
            )
        )
    ).one()
    assert tuple(row) == ("mean", "stage", "pollination")
    # The crop itself sets nothing: Medjool's setting is its own.
    crop_row = (
        await admin_session.execute(
            text("SELECT gdd_method, gdd_start_kind FROM public.crops WHERE code='date_palm'")
        )
    ).one()
    assert tuple(crop_row) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "assignment",
    [
        "gdd_method = 'average'",
        "gdd_start_kind = 'date', gdd_start_value = '3-1'",
        "gdd_start_kind = 'planting', gdd_start_value = 'pollination'",
        "gdd_start_kind = NULL, gdd_start_value = '03-01'",
        "gdd_start_kind = 'stage', gdd_start_value = NULL",
    ],
)
async def test_checks_reject_a_bad_setting(admin_session: AsyncSession, assignment: str) -> None:
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            text(f"UPDATE public.crops SET {assignment} WHERE code = 'date_palm'")
        )
    await admin_session.rollback()


async def _seed_medjool_block(admin_session: AsyncSession, schema: str):
    crop_id = (
        await admin_session.execute(text("SELECT id FROM public.crops WHERE code='date_palm'"))
    ).scalar_one()
    variety_id = (
        await admin_session.execute(
            text("SELECT id FROM public.crop_varieties WHERE path='date_palm.medjool'")
        )
    ).scalar_one()
    farm_id, block_id, bc_id = uuid4(), uuid4(), uuid4()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, 'HU', 'HU Farm', "
            " ST_GeomFromEWKT('SRID=4326;MULTIPOLYGON(((31.2 30.0,31.21 30.0,31.21 30.01,31.2 30.01,31.2 30.0)))'), "
            " 'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=_UUID)),
        {"id": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2) "
            "VALUES (:id, :farm, 'B1', "
            " ST_GeomFromEWKT('SRID=4326;POLYGON((31.2 30.0,31.201 30.0,31.201 30.001,31.2 30.001,31.2 30.0))'), "
            " 'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry, "
            " 'SRID=4326;POINT(0 0)'::geometry, 0)"
        ).bindparams(bindparam("id", type_=_UUID), bindparam("farm", type_=_UUID)),
        {"id": block_id, "farm": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO block_crops (id, block_id, crop_id, crop_variety_id, crop_path, "
            " season_label, planting_date, effective_from, is_current, status) "
            "VALUES (:id, :block, :crop, :variety, 'date_palm.medjool', '2026', "
            " '2018-03-01', '2018-03-01', TRUE, 'growing')"
        ).bindparams(
            bindparam("id", type_=_UUID),
            bindparam("block", type_=_UUID),
            bindparam("crop", type_=_UUID),
            bindparam("variety", type_=_UUID),
        ),
        {"id": bc_id, "block": block_id, "crop": crop_id, "variety": variety_id},
    )
    # Entered pollination last season and again this season: the latest wins.
    for when in (datetime(2025, 2, 6, 8, tzinfo=UTC), datetime(2026, 3, 1, 8, tzinfo=UTC)):
        await admin_session.execute(
            text(
                "INSERT INTO growth_stage_logs (block_id, block_crop_id, stage, source, "
                " transition_date) VALUES (:block, :bc, 'pollination', 'manual', :at)"
            ).bindparams(bindparam("block", type_=_UUID), bindparam("bc", type_=_UUID)),
            {"block": block_id, "bc": bc_id, "at": when},
        )
    # A transition into another stage after it does not move the start.
    await admin_session.execute(
        text(
            "INSERT INTO growth_stage_logs (block_id, block_crop_id, stage, source, "
            " transition_date) VALUES (:block, :bc, 'fruit_set', 'manual', :at)"
        ).bindparams(bindparam("block", type_=_UUID), bindparam("bc", type_=_UUID)),
        {"block": block_id, "bc": bc_id, "at": datetime(2026, 3, 3, 8, tzinfo=UTC)},
    )
    for day, tmin, tmax in [
        (date(2026, 2, 28), 20, 40),  # before the start
        (date(2026, 3, 1), 20, 36),  # (20 + 36) / 2 - 18 = 10
        (date(2026, 3, 2), None, 36),  # no Tmin: skipped
        (date(2026, 3, 3), 22, 30),  # 8
        (date(2026, 3, 4), 24, 32),  # 10
    ]:
        await admin_session.execute(
            text(
                "INSERT INTO weather_derived_daily (farm_id, date, temp_min_c, temp_max_c) "
                "VALUES (:farm, :d, :tmin, :tmax)"
            ).bindparams(bindparam("farm", type_=_UUID)),
            {"farm": farm_id, "d": day, "tmin": tmin, "tmax": tmax},
        )
    await admin_session.commit()
    return farm_id, bc_id


@pytest.mark.asyncio
async def test_loader_counts_medjool_from_the_latest_pollination(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="heat-units", name="Heat Units", contact_email="ops@heat-units.test"
    )
    schema = await _schema_for(admin_session, tenant.tenant_id)
    farm_id, bc_id = await _seed_medjool_block(admin_session, schema)

    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    snap = await load_heat_units_snapshot(
        admin_session, admin_session, block_crop_id=bc_id, farm_id=farm_id, today=date(2026, 3, 4)
    )
    assert snap == {"total": Decimal("28"), "today": Decimal("10"), "days_since_start": 3}

    # The block's own start (tenant 0109) wins over the stage.
    await admin_session.execute(
        text("UPDATE block_crops SET gdd_start_date = '2026-03-03' WHERE id = :id").bindparams(
            bindparam("id", type_=_UUID)
        ),
        {"id": bc_id},
    )
    await admin_session.commit()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    snap = await load_heat_units_snapshot(
        admin_session, admin_session, block_crop_id=bc_id, farm_id=farm_id, today=date(2026, 3, 4)
    )
    assert snap == {"total": Decimal("18"), "today": Decimal("10"), "days_since_start": 1}

    # A start after today, a missing farm or no crop: empty, so trees fail closed.
    assert (
        await load_heat_units_snapshot(
            admin_session,
            admin_session,
            block_crop_id=bc_id,
            farm_id=farm_id,
            today=date(2026, 3, 2),
        )
        == {}
    )
    assert (
        await load_heat_units_snapshot(
            admin_session, admin_session, block_crop_id=bc_id, farm_id=None
        )
        == {}
    )
    assert (
        await load_heat_units_snapshot(
            admin_session, admin_session, block_crop_id=None, farm_id=farm_id
        )
        == {}
    )
    await admin_session.execute(text("SET search_path TO public"))


@pytest.mark.asyncio
async def test_catalogue_api_sets_heat_units_down_the_taxonomy() -> None:
    context = make_context(
        user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN
    )
    code = f"hu-{uuid4().hex[:6]}"
    async with AsyncClient(
        transport=ASGITransport(app=build_app(context)), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/admin/crops",
            json={
                "code": code,
                "name_en": "Heat crop",
                "name_ar": "محصول حراري",
                "category": "cereal",
                "classification_depth": "variety_strain",
                "gdd_base_temp_c": 10,
                "gdd_upper_temp_c": 30,
                "gdd_method": "min_max_cutoff",
                "gdd_start_kind": "planting",
            },
        )
        assert r.status_code == 201, r.text
        crop = r.json()
        assert (crop["gdd_method"], crop["gdd_start_kind"], crop["gdd_start_value"]) == (
            "min_max_cutoff",
            "planting",
            None,
        )

        rv = await client.post(
            f"/api/v1/admin/crops/{crop['id']}/varieties",
            json={
                "code": "v1",
                "name_en": "V1",
                "name_ar": "صنف 1",
                "gdd_start_kind": "date",
                "gdd_start_value": "03-01",
            },
        )
        assert rv.status_code == 201, rv.text
        variety = rv.json()
        assert (variety["gdd_method"], variety["gdd_start_value"]) == (None, "03-01")

        # A date start without MM-DD is refused before it reaches the CHECK.
        bad = await client.patch(
            f"/api/v1/admin/crop-varieties/{variety['id']}", json={"gdd_start_value": "March"}
        )
        assert bad.status_code == 422, bad.text

        # Switching the kind to planting drops the date the request did not resend.
        rp = await client.patch(
            f"/api/v1/admin/crop-varieties/{variety['id']}", json={"gdd_start_kind": "planting"}
        )
        assert rp.status_code == 200, rp.text
        assert (rp.json()["gdd_start_kind"], rp.json()["gdd_start_value"]) == ("planting", None)

        rs = await client.post(
            f"/api/v1/admin/crop-varieties/{variety['id']}/strains",
            json={"code": "s1", "name_en": "S1", "name_ar": "سلالة 1", "gdd_method": "max"},
        )
        assert rs.status_code == 201, rs.text
        assert rs.json()["gdd_method"] == "max"
