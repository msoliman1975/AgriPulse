"""The metric coordinate system is per farm, not a fixed UTM zone 36 North.

Migration 0082 moved the zone out of the two trigger functions and onto
``farms.utm_srid``. These tests hold the four properties that change is worth
having:

  * A farm outside Egypt gets a correct ``area_m2``. Before 0082 every
    boundary went through ``ST_Transform(..., 32636)``, which does not fail
    outside zone 36 — it returns a finite, wrong number.
  * The zone is derived once and never recomputed, so reshaping a farm cannot
    move it between coordinate systems and change its ``aoi_hash``.
  * Blocks take their farm's zone, so a farm and its blocks stay cut against
    each other.
  * Southern-hemisphere farms get a 327xx zone rather than a 326xx one.

``ST_Area(boundary::geography)`` is the reference: it is the geodesic area on
the WGS84 spheroid, computed independently of any projection. A UTM zone is
accurate to about 0.08% over a small polygon, so the tolerance below is 0.1%.
The same comparison in the wrong zone is off by 4.8% in Riyadh and by a factor
of 5.3 in Sao Paulo.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]

#: Relative area error we accept between the UTM projection and the geodesic
#: reference. UTM's scale factor is 0.9996 on the central meridian, so a small
#: polygon is about 0.08% small there and 0.08% large at the zone edge.
_AREA_TOLERANCE = 0.001


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, Any]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [lon, lat],
                    [lon + side, lat],
                    [lon + side, lat + side],
                    [lon, lat + side],
                    [lon, lat],
                ]
            ]
        ],
    }


def _block_square(lon: float, lat: float, side: float = 0.002) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon, lat],
                [lon + side, lat],
                [lon + side, lat + side],
                [lon, lat + side],
                [lon, lat],
            ]
        ],
    }


async def _create_user_in_tenant(session: AsyncSession, *, tenant_id: Any, user_id: Any) -> None:
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": f"u-{user_id}@example.test",
            "name": "Test User",
        },
    )
    membership_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant_id},
    )
    await session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    await session.commit()


async def _tenant_app(session: AsyncSession, slug: str) -> tuple[Any, Any]:
    """A tenant with one TenantAdmin, plus an app wired to that context."""
    tenancy = get_tenant_service(session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=slug,
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, build_app(context)


async def _farm_geometry_row(session: AsyncSession, *, schema: str, farm_id: str) -> dict[str, Any]:
    await session.execute(text(f'SET search_path TO "{schema}", public'))
    try:
        row = (
            (
                await session.execute(
                    text(
                        """
                        SELECT utm_srid,
                               ST_SRID(boundary_utm)     AS geom_srid,
                               area_m2,
                               aoi_hash,
                               ST_Area(boundary::geography) AS geodesic_area_m2
                          FROM farms
                         WHERE id = :id
                        """
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": farm_id},
                )
            )
            .mappings()
            .one()
        )
        return dict(row)
    finally:
        await session.execute(text("RESET search_path"))


def _relative_area_error(row: dict[str, Any]) -> float:
    projected = float(row["area_m2"])
    geodesic = float(row["geodesic_area_m2"])
    return abs(projected - geodesic) / geodesic


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slug", "lon", "lat", "expected_srid"),
    [
        ("utm-cairo", 31.2, 30.0, 32636),  # Egypt, the only case that worked before
        ("utm-riyadh", 46.7, 24.7, 32638),  # 4.8% too large under zone 36
        ("utm-madrid", -3.7, 40.4, 32630),  # 26% too large under zone 36
        ("utm-saopaulo", -46.6, -23.5, 32723),  # 5.3x too large, and southern
    ],
)
async def test_farm_gets_its_own_zone_and_a_correct_area(
    admin_session: AsyncSession, slug: str, lon: float, lat: float, expected_srid: int
) -> None:
    tenant, app = await _tenant_app(admin_session, slug)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-Z",
                "name": "Zoned farm",
                "boundary": _square(lon, lat),
                "farm_type": "commercial",
            },
        )
    assert resp.status_code == 201, resp.text
    farm_id = resp.json()["id"]

    row = await _farm_geometry_row(admin_session, schema=tenant.schema_name, farm_id=farm_id)
    assert row["utm_srid"] == expected_srid
    assert row["geom_srid"] == expected_srid
    error = _relative_area_error(row)
    assert error < _AREA_TOLERANCE, f"area off by {error:.4%} in EPSG:{expected_srid}"


@pytest.mark.asyncio
async def test_reshaping_a_farm_never_moves_its_zone(admin_session: AsyncSession) -> None:
    """A farm keeps the zone it was created in, even if it moves out of it.

    This is the property that protects imagery. ``aoi_hash`` is a SHA-256 of
    the UTM text, and it is how a farm and its blocks are matched to their
    stored rasters. If the zone were recomputed on every write, an ordinary
    boundary edit near a zone edge would silently orphan the imagery.
    """
    tenant, app = await _tenant_app(admin_session, "utm-reshape")

    # Longitude 27 is zone 35; longitude 33 is zone 36. Both are inside Egypt,
    # which is exactly why Egypt's own farms cannot be re-zoned casually.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-R",
                "name": "Reshaped farm",
                "boundary": _square(27.0, 26.0),
                "farm_type": "commercial",
            },
        )
        assert resp.status_code == 201, resp.text
        farm_id = resp.json()["id"]

        before = await _farm_geometry_row(admin_session, schema=tenant.schema_name, farm_id=farm_id)
        assert before["utm_srid"] == 32635

        resp = await c.patch(
            f"/api/v1/farms/{farm_id}",
            json={"boundary": _square(33.0, 26.0)},
        )
        assert resp.status_code == 200, resp.text

    after = await _farm_geometry_row(admin_session, schema=tenant.schema_name, farm_id=farm_id)
    assert after["utm_srid"] == 32635, "the zone must not follow the boundary"
    assert after["geom_srid"] == 32635
    assert after["aoi_hash"] != before["aoi_hash"], "a new shape is a new AOI"


@pytest.mark.asyncio
async def test_a_block_takes_its_farms_zone(admin_session: AsyncSession) -> None:
    tenant, app = await _tenant_app(admin_session, "utm-block")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-B",
                "name": "Block host",
                "boundary": _square(46.7, 24.7),
                "farm_type": "commercial",
            },
        )
        assert resp.status_code == 201, resp.text
        farm_id = resp.json()["id"]

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "BLK-1",
                "name": "Block one",
                "boundary": _block_square(46.701, 24.701),
            },
        )
        assert resp.status_code == 201, resp.text
        block_id = resp.json()["id"]

    await admin_session.execute(text(f'SET search_path TO "{tenant.schema_name}", public'))
    try:
        row = (
            (
                await admin_session.execute(
                    text(
                        """
                        SELECT ST_SRID(b.boundary_utm)      AS block_srid,
                               f.utm_srid                   AS farm_srid,
                               b.area_m2,
                               ST_Area(b.boundary::geography) AS geodesic_area_m2
                          FROM blocks b
                          JOIN farms f ON f.id = b.farm_id
                         WHERE b.id = :id
                        """
                    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                    {"id": block_id},
                )
            )
            .mappings()
            .one()
        )
    finally:
        await admin_session.execute(text("RESET search_path"))

    assert row["block_srid"] == 32638
    assert row["farm_srid"] == 32638
    error = _relative_area_error(dict(row))
    assert error < _AREA_TOLERANCE, f"block area off by {error:.4%}"


def _upgrade_tenant_schema(schema: str, revision: str) -> None:
    """Run the tenant migration chain against one schema, to one revision.

    The same entry point `AlembicTenantMigrator` uses, so this exercises the
    real migration rather than a copy of its SQL.
    """
    from argparse import Namespace
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    import app

    ini = Path(app.__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini), ini_section="tenant")
    cfg.cmd_opts = Namespace(x=[f"schema={schema}"])
    command.upgrade(cfg, revision)


#: Schema-qualified throughout on purpose. `SET search_path` is connection
#: state that rides the pooled connection, and this test brackets a DDL
#: migration — leaving that state behind would surface as an unrelated
#: failure in whatever test drew the connection next.
_BACKFILL_SCHEMA = "tenant_utm_backfill"


@pytest.mark.asyncio
async def test_migration_0082_leaves_existing_farms_in_zone_36(
    admin_session: AsyncSession,
) -> None:
    """A farm that exists before 0082 keeps zone 36, byte for byte.

    This is the property the whole design is built around. ``aoi_hash`` is a
    SHA-256 of ``ST_AsText(boundary_utm)``, and it is the key under which a
    farm's and a block's rasters are stored. A migration that re-zoned
    existing rows would move every hash and orphan every raster.

    The farm here sits at longitude 27, which the new rule would put in zone
    35. It must still come out of the migration in zone 36.
    """
    import asyncio

    schema = _BACKFILL_SCHEMA
    farm_id = uuid4()
    block_id = uuid4()

    await admin_session.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await admin_session.execute(text(f'CREATE SCHEMA "{schema}"'))
    await admin_session.commit()

    # Stop one revision short of the change under test.
    await asyncio.to_thread(_upgrade_tenant_schema, schema, "0081")

    await admin_session.execute(
        text(
            f"""
            INSERT INTO "{schema}".farms
                   (id, code, name, boundary, boundary_utm, centroid, area_m2)
            VALUES (
                :id, 'PRE-0082', 'Pre-migration farm',
                ST_GeomFromEWKT(
                    'SRID=4326;MULTIPOLYGON(((27.0 26.0, 27.005 26.0, '
                    '27.005 26.005, 27.0 26.005, 27.0 26.0)))'
                ),
                'SRID=32636;MULTIPOLYGON(((0 0,1 0,1 1,0 1,0 0)))'::geometry,
                'SRID=4326;POINT(0 0)'::geometry,
                0
            )
            """
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": farm_id},
    )
    await admin_session.execute(
        text(
            f"""
            INSERT INTO "{schema}".blocks
                   (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, aoi_hash)
            VALUES (
                :id, :farm, 'PRE-B1',
                ST_GeomFromEWKT(
                    'SRID=4326;POLYGON((27.001 26.001, 27.003 26.001, '
                    '27.003 26.003, 27.001 26.003, 27.001 26.001))'
                ),
                'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry,
                'SRID=4326;POINT(0 0)'::geometry,
                0, ''
            )
            """
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("farm", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": block_id, "farm": farm_id},
    )
    await admin_session.commit()

    read_sql = text(
        f"""
        SELECT f.aoi_hash AS farm_hash, f.area_m2 AS farm_area,
               ST_SRID(f.boundary_utm) AS farm_srid,
               b.aoi_hash AS block_hash, b.area_m2 AS block_area,
               ST_SRID(b.boundary_utm) AS block_srid
          FROM "{schema}".farms f
          JOIN "{schema}".blocks b ON b.farm_id = f.id
         WHERE f.id = :id
        """
    ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True)))

    before = dict((await admin_session.execute(read_sql, {"id": farm_id})).mappings().one())
    assert before["farm_srid"] == 32636
    assert before["block_srid"] == 32636
    await admin_session.commit()

    await asyncio.to_thread(_upgrade_tenant_schema, schema, "0082")

    after = dict((await admin_session.execute(read_sql, {"id": farm_id})).mappings().one())
    zone = (
        await admin_session.execute(
            text(f'SELECT utm_srid FROM "{schema}".farms WHERE id = :id').bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": farm_id},
        )
    ).scalar_one()
    await admin_session.commit()

    assert zone == 32636, "the backfill must not re-zone anyone"
    assert after["farm_srid"] == 32636
    assert after["block_srid"] == 32636
    assert after["farm_hash"] == before["farm_hash"], "farm rasters would be orphaned"
    assert after["block_hash"] == before["block_hash"], "block rasters would be orphaned"
    assert after["farm_area"] == before["farm_area"]
    assert after["block_area"] == before["block_area"]
