"""Integration tests for farm CRUD endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.farms.auto_grid import cell_size_for_max_area_m2
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context

M2_PER_FEDDAN = 4200.83

pytestmark = [pytest.mark.integration]


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
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


async def _create_user_in_tenant(session: AsyncSession, *, tenant_id, user_id) -> None:
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
async def test_create_and_get_farm(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-crud-1",
        name="Farms CRUD",
        contact_email="ops@farms-crud.test",
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
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-1",
                "name": "Acme Farm 1",
                "boundary": _square(31.2, 30.0),
                "farm_type": "commercial",
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "FARM-1"
    assert body["is_active"] is True
    assert body["active_to"] is None
    assert body["area_unit"] == "feddan"
    assert float(body["area_value"]) > 0
    farm_id = body["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(f"/api/v1/farms/{farm_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == farm_id


@pytest.mark.asyncio
async def test_create_rejects_out_of_egypt_geometry(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-bbox",
        name="OOB",
        contact_email="ops@farms-bbox.test",
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
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-OOB",
                "name": "Out of bounds",
                # Tripoli — outside Egypt's bbox.
                "boundary": _square(13.0, 32.0),
                "farm_type": "commercial",
            },
        )
    assert resp.status_code == 422
    assert "Egypt" in resp.json().get("title", "") or "egypt" in resp.text.lower()


@pytest.mark.asyncio
async def test_auto_grid_by_max_area_derives_and_echoes_cell_size(
    admin_session: AsyncSession,
) -> None:
    """The auto-grid endpoint accepts a per-block max area (canonical m²),
    derives the grid cell from it, and never emits a block larger than that
    derived cell (clipping only shrinks boundary cells)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-autogrid-area",
        name="AutoGrid Area",
        contact_email="ops@farms-autogrid-area.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(context)

    # ~1.1 km square farm so the grid yields several full interior cells.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-AG",
                "name": "AutoGrid Farm",
                "boundary": _square(31.2, 30.0, side=0.01),
            },
        )
        assert resp.status_code == 201, resp.text
        farm_id = resp.json()["id"]

        # 5 feddan cap → ~145 m square cell.
        max_area_m2 = 5 * M2_PER_FEDDAN
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks/auto-grid",
            json={"max_area_m2": max_area_m2},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_cell = cell_size_for_max_area_m2(max_area_m2)
    assert body["cell_size_m"] == expected_cell
    assert len(body["candidates"]) > 0
    # No candidate exceeds a full derived cell; clipping can only shrink.
    full_cell_area = expected_cell * expected_cell
    assert all(float(c["area_m2"]) <= full_cell_area + 1.0 for c in body["candidates"])
    # At least one full interior cell hits (approximately) the cap.
    assert any(float(c["area_m2"]) >= full_cell_area * 0.99 for c in body["candidates"])


@pytest.mark.asyncio
async def test_auto_grid_by_cell_size_still_supported(admin_session: AsyncSession) -> None:
    """The legacy cell_size_m path keeps working and is echoed verbatim."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-autogrid-cell",
        name="AutoGrid Cell",
        contact_email="ops@farms-autogrid-cell.test",
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
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-AGC",
                "name": "AutoGrid Cell Farm",
                "boundary": _square(31.2, 30.0, side=0.01),
            },
        )
        farm_id = resp.json()["id"]

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks/auto-grid",
            json={"cell_size_m": 300},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cell_size_m"] == 300
    assert len(body["candidates"]) > 0


@pytest.mark.asyncio
async def test_archive_then_get_returns_404(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="farms-archive",
        name="Archive",
        contact_email="ops@farms-archive.test",
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
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-A",
                "name": "Will Archive",
                "boundary": _square(31.2, 30.0),
            },
        )
        farm_id = resp.json()["id"]

        del_resp = await c.delete(f"/api/v1/farms/{farm_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["farm_id"] == farm_id
        assert del_resp.json()["block_count"] == 0

        get_resp = await c.get(f"/api/v1/farms/{farm_id}")
        assert get_resp.status_code == 404
