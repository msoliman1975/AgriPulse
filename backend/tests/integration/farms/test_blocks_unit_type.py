"""Integration tests for `blocks.unit_type` polymorphism (PR-1).

Confirms migration 0006 adds the columns + check constraints, that the
default for new rows is ``'block'``, and that the service-layer
validation rejects illegal pivot_sector parents (different farm,
non-pivot, missing).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _polygon(lon: float, lat: float, side: float = 0.003) -> dict[str, object]:
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


async def _bootstrap_tenant(admin_session: AsyncSession, slug: str) -> tuple[object, object]:
    """Create tenant + admin user; return (tenant, request_context)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"PR-1 {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, context


async def _create_farm(client: AsyncClient, *, code: str = "FARM-PR1") -> str:
    resp = await client.post(
        "/api/v1/farms",
        json={
            "code": code,
            "name": f"PR-1 Farm {code}",
            "boundary": _square(31.20, 30.10),
            "farm_type": "commercial",
            "tags": [],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Schema-level: migration applied, columns + constraints exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unit_type_columns_exist(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr1-cols",
        name="PR-1 Cols",
        contact_email="ops@pr1-cols.test",
    )
    rows = (
        await admin_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = 'blocks' "
                "AND column_name IN ('unit_type','parent_unit_id','irrigation_geometry')"
            ),
            {"s": tenant.schema_name},
        )
    ).all()
    names = {r[0] for r in rows}
    assert names == {"unit_type", "parent_unit_id", "irrigation_geometry"}


@pytest.mark.asyncio
async def test_unit_type_check_constraint_rejects_unknown(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr1-ck",
        name="PR-1 Check",
        contact_email="ops@pr1-ck.test",
    )
    # Pin search_path first; psycopg/asyncpg execute a single statement
    # per call, so the SET and INSERT have to be separate executes.
    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    # Direct INSERT bypassing the service: the CHECK should kick in.
    with pytest.raises(IntegrityError):
        await admin_session.execute(
            text(
                "INSERT INTO blocks ("
                "  id, farm_id, code, boundary, boundary_utm, centroid, area_m2, aoi_hash, "
                "  unit_type"
                ") VALUES ("
                "  gen_random_uuid(), gen_random_uuid(), 'BAD',"
                "  'SRID=4326;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry,"
                "  'SRID=32636;POLYGON((0 0,1 0,1 1,0 1,0 0))'::geometry,"
                "  'SRID=4326;POINT(0 0)'::geometry,"
                "  0, '', 'kite'"
                ")"
            )
        )
    await admin_session.rollback()


# ---------------------------------------------------------------------------
# Service-level: defaults, parent rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_create_defaults_to_unit_type_block(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "pr1-default")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-DEF", "boundary": _polygon(31.21, 30.11)},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["unit_type"] == "block"
    assert body["parent_unit_id"] is None
    assert body["irrigation_geometry"] is None


@pytest.mark.asyncio
async def test_pivot_creation_round_trip(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "pr1-pivot")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "PIVOT-1",
                "boundary": _polygon(31.22, 30.11),
                "unit_type": "pivot",
                "irrigation_system": "pivot",
                "irrigation_geometry": {
                    "center": {"lat": 30.111, "lon": 31.221},
                    "radius_m": 200.0,
                },
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["unit_type"] == "pivot"
    assert body["irrigation_geometry"] == {
        "center": {"lat": 30.111, "lon": 31.221},
        "radius_m": 200.0,
    }


@pytest.mark.asyncio
async def test_pivot_sector_requires_pivot_parent_on_same_farm(
    admin_session: AsyncSession,
) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "pr1-sector-ok")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        # Create a pivot first.
        pivot = (
            await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={
                    "code": "PIVOT-A",
                    "boundary": _polygon(31.23, 30.11),
                    "unit_type": "pivot",
                    "irrigation_system": "pivot",
                },
            )
        ).json()
        pivot_id = pivot["id"]

        # Sector referencing it — happy path.
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "PIVOT-A-S1",
                "boundary": _polygon(31.231, 30.111, side=0.001),
                "unit_type": "pivot_sector",
                "parent_unit_id": pivot_id,
                "irrigation_geometry": {
                    "start_angle_deg": 0,
                    "end_angle_deg": 90,
                },
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["unit_type"] == "pivot_sector"
        assert resp.json()["parent_unit_id"] == pivot_id


@pytest.mark.asyncio
async def test_pivot_sector_without_parent_rejected(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "pr1-sector-noparent")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "PIVOT-S",
                "boundary": _polygon(31.24, 30.11),
                "unit_type": "pivot_sector",
            },
        )
    assert resp.status_code == 422, resp.text
    assert "parent_unit_id" in resp.text


@pytest.mark.asyncio
async def test_pivot_sector_parent_must_be_pivot(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "pr1-sector-wrongkind")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        # Parent is a plain block, not a pivot.
        plain = (
            await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={"code": "B-PLAIN", "boundary": _polygon(31.25, 30.11)},
            )
        ).json()
        plain_id = plain["id"]

        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "PIVOT-S",
                "boundary": _polygon(31.251, 30.111, side=0.001),
                "unit_type": "pivot_sector",
                "parent_unit_id": plain_id,
            },
        )
    assert resp.status_code == 422, resp.text
    assert "pivot_sector parent must be a pivot" in resp.text


@pytest.mark.asyncio
async def test_pivot_sector_parent_must_share_farm(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr1-sector-crossfarm",
        name="PR-1 Sector Cross Farm",
        contact_email="ops@pr1-cf.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Two farms.
        farm_a = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "FARM-A",
                    "name": "Farm A",
                    "boundary": _square(31.20, 30.10),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()
        farm_b = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "FARM-B",
                    "name": "Farm B",
                    "boundary": _square(31.30, 30.10),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()
        # Pivot on farm A.
        pivot = (
            await client.post(
                f"/api/v1/farms/{farm_a['id']}/blocks",
                json={
                    "code": "PIVOT-A",
                    "boundary": _polygon(31.21, 30.11),
                    "unit_type": "pivot",
                    "irrigation_system": "pivot",
                },
            )
        ).json()

        # Sector on farm B referencing pivot on farm A — must be rejected.
        resp = await client.post(
            f"/api/v1/farms/{farm_b['id']}/blocks",
            json={
                "code": "PIVOT-S",
                "boundary": _polygon(31.31, 30.11, side=0.001),
                "unit_type": "pivot_sector",
                "parent_unit_id": pivot["id"],
            },
        )
    assert resp.status_code == 422, resp.text
    assert "same farm" in resp.text


@pytest.mark.asyncio
async def test_block_with_parent_unit_id_rejected(admin_session: AsyncSession) -> None:
    """`unit_type='block'` cannot carry parent_unit_id — only pivot_sector does."""
    _tenant, context = await _bootstrap_tenant(admin_session, "pr1-block-parent")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        pivot = (
            await client.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={
                    "code": "PIVOT-A",
                    "boundary": _polygon(31.22, 30.11),
                    "unit_type": "pivot",
                    "irrigation_system": "pivot",
                },
            )
        ).json()
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B-WRONG",
                "boundary": _polygon(31.23, 30.11),
                "unit_type": "block",
                "parent_unit_id": pivot["id"],
            },
        )
    assert resp.status_code == 422, resp.text


# Suppress unused-import warning for UUID — used implicitly via test wiring.
_ = UUID
