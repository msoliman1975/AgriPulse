"""PR-B1: block_crops canopy_size_class + growth_stage_locked.

Canopy size is validated against the crop's resolved size_classes lookup
(mango ships small/medium/large via migration 0033); the lock flag and
size round-trip through the new PATCH endpoint.
"""

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


def _polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [[lon, lat], [lon + side, lat], [lon + side, lat + side], [lon, lat + side], [lon, lat]]
        ],
    }


def _multipolygon(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    return {"type": "MultiPolygon", "coordinates": [_polygon(lon, lat, side)["coordinates"]]}


pytestmark = [pytest.mark.integration]


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[object, str]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id, "sub": f"kc-{user_id}", "email": f"u@{slug}.test", "name": "U"},
    )
    membership_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant.tenant_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    await admin_session.commit()
    ctx = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    return build_app(ctx), str(tenant.tenant_id)


@pytest.mark.asyncio
async def test_canopy_size_assign_validate_and_update(admin_session: AsyncSession) -> None:
    app, _ = await _bootstrap(admin_session, "bc-size")
    # Mango (variety_strain) + the 0030 alphonso/short example; size classes from 0033.
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

    base = {
        "crop_id": str(crop_id),
        "crop_variety_id": str(variety_id),
        "crop_variety_strain_id": str(strain_id),
        "season_label": "2026",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "SZ", "name": "Size", "boundary": _multipolygon(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _polygon(31.2, 30.0)},
        )
        block_id = block.json()["id"]

        # Invalid size class -> 422.
        bad = await c.post(
            f"/api/v1/blocks/{block_id}/crop-assignments",
            json={**base, "canopy_size_class": "huge", "make_current": True},
        )
        assert bad.status_code == 422, bad.text

        # Valid size class -> 201 and round-trips.
        good = await c.post(
            f"/api/v1/blocks/{block_id}/crop-assignments",
            json={**base, "canopy_size_class": "medium", "make_current": True},
        )
        assert good.status_code == 201, good.text
        bc = good.json()
        assert bc["canopy_size_class"] == "medium"
        assert bc["growth_stage_locked"] is False
        bc_id = bc["id"]

        # PATCH: set lock + change size.
        patched = await c.patch(
            f"/api/v1/blocks/{block_id}/crop-assignments/{bc_id}",
            json={"growth_stage_locked": True, "canopy_size_class": "large"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["growth_stage_locked"] is True
        assert patched.json()["canopy_size_class"] == "large"

        # PATCH with invalid size -> 422.
        bad_patch = await c.patch(
            f"/api/v1/blocks/{block_id}/crop-assignments/{bc_id}",
            json={"canopy_size_class": "tiny"},
        )
        assert bad_patch.status_code == 422, bad_patch.text
