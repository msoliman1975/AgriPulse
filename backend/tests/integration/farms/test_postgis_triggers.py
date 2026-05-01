"""Integration test: PostGIS triggers populate computed columns correctly.

Inserts a farm with a known boundary and verifies the trigger-computed
boundary_utm, centroid, and area_m2 match expected values within
floating-point tolerance.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_farm_trigger_computes_centroid_and_area(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="trig-farm",
        name="Trigger",
        contact_email="ops@trig-farm.test",
    )

    schema = tenant.schema_name

    # Insert a 0.005° x 0.005° farm at (31.0, 30.0).
    farm_id = uuid4()
    boundary_ewkt = (
        "SRID=4326;MULTIPOLYGON((("
        "31.0 30.0, 31.005 30.0, 31.005 30.005, 31.0 30.005, 31.0 30.0"
        ")))"
    )
    # Use SET (session-scope) so the search_path survives the commit
    # below; SET LOCAL is per-transaction.
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, "
            "area_m2, farm_type, status) "
            "VALUES (:id, 'F-T1', 'Trigger Farm', ST_GeomFromEWKT(:b), "
            "'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            "'SRID=4326;POINT(0 0)'::geometry, 0, 'commercial', 'active')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": farm_id, "b": boundary_ewkt},
    )
    await admin_session.commit()

    # The two queries below interpolate `schema`, the tenant schema
    # name fresh from `tenancy.create_tenant(...)`. It's validated by
    # `sanitize_tenant_schema` so the f-string here isn't a real
    # injection vector — disable S608 for these two reads.
    sql = (
        "SELECT ST_X(centroid) AS lon, ST_Y(centroid) AS lat, area_m2, "  # noqa: S608
        "ST_SRID(boundary_utm) AS utm_srid "
        f"FROM {schema}.farms WHERE id = :id"
    )
    row = (
        await admin_session.execute(
            text(sql).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": farm_id},
        )
    ).one()

    # Centroid should be ~midpoint of the 0.005° square.
    assert abs(row.lon - 31.0025) < 1e-6
    assert abs(row.lat - 30.0025) < 1e-6
    # UTM 36N
    assert row.utm_srid == 32636
    # ~0.005° x 0.005° at lat 30°N is roughly 480m x 555m → ~266_000 m².
    assert 200_000 < row.area_m2 < 320_000


@pytest.mark.asyncio
async def test_block_trigger_computes_aoi_hash(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="trig-block",
        name="Trigger Block",
        contact_email="ops@trig-block.test",
    )
    schema = tenant.schema_name

    farm_id = uuid4()
    block_id = uuid4()
    await admin_session.execute(text(f"SET search_path TO {schema}, public"))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, "
            "area_m2, farm_type, status) "
            "VALUES (:id, 'F-1', 'F1', ST_GeomFromEWKT(:b), "
            "'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry, "
            "'SRID=4326;POINT(0 0)'::geometry, 0, 'commercial', 'active')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": farm_id,
            "b": (
                "SRID=4326;MULTIPOLYGON(((31.0 30.0,31.005 30.0,"
                "31.005 30.005,31.0 30.005,31.0 30.0)))"
            ),
        },
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, "
            "area_m2, aoi_hash, status) "
            "VALUES (:bid, :fid, 'B-1', ST_GeomFromEWKT(:b), "
            "'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry, "
            "'SRID=4326;POINT(0 0)'::geometry, 0, '', 'active')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "bid": block_id,
            "fid": farm_id,
            "b": (
                "SRID=4326;POLYGON((31.0 30.0,31.002 30.0," "31.002 30.002,31.0 30.002,31.0 30.0))"
            ),
        },
    )
    await admin_session.commit()

    sql = f"SELECT aoi_hash, area_m2 FROM {schema}.blocks WHERE id = :id"  # noqa: S608
    row = (
        await admin_session.execute(
            text(sql).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
            {"id": block_id},
        )
    ).one()
    assert len(row.aoi_hash) == 64  # SHA-256 hex
    assert row.area_m2 > 0
