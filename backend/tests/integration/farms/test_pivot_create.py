"""Integration test for the pivot+sector atomic create endpoint."""

from __future__ import annotations

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


def _square(lon: float, lat: float, side: float = 0.02) -> dict[str, object]:
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


async def _create_user_in_tenant(session, *, tenant_id, user_id):
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


@pytest.mark.asyncio
async def test_create_pivot_with_4_sectors(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pivot-create",
        name="Pivot",
        contact_email="ops@pivot-create.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        assert farm.status_code == 201, farm.text
        farm_id = farm.json()["id"]

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/pivots",
            json={
                "code": "P1",
                "name": "Pivot 1",
                "center": {"lat": 30.005, "lon": 31.205},
                "radius_m": 300,
                "sector_count": 4,
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["pivot"]["code"] == "P1"
    assert body["pivot"]["unit_type"] == "pivot"
    assert body["pivot"]["parent_unit_id"] is None
    # Circle of radius 300m → area ~ pi*300² ≈ 282,743 m². Spherical
    # approximation + 64-vertex polygon trims a bit; accept ±5%.
    pivot_area = float(body["pivot"]["area_m2"])
    assert 269_000 < pivot_area < 297_000

    assert len(body["sectors"]) == 4
    for i, s in enumerate(body["sectors"], start=1):
        assert s["code"] == f"P1-S{i}"
        assert s["unit_type"] == "pivot_sector"
        assert s["parent_unit_id"] == body["pivot"]["id"]
    # Each equal sector covers ~25% of the pivot area.
    sector_areas = [float(s["area_m2"]) for s in body["sectors"]]
    for a in sector_areas:
        assert 65_000 < a < 80_000
    # Sectors sum to roughly the pivot (allow 1% slack for spherical-vs-flat).
    total = sum(sector_areas)
    assert abs(total - pivot_area) / pivot_area < 0.02


@pytest.mark.asyncio
async def test_create_pivot_rejects_bad_radius(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pivot-bad",
        name="Pivot",
        contact_email="ops@pivot-bad.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/pivots",
            json={
                "code": "P1",
                "center": {"lat": 30.005, "lon": 31.205},
                "radius_m": -5,
                "sector_count": 4,
            },
        )
    assert resp.status_code == 422
