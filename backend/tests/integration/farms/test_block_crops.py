"""Integration test: block_crops `is_current` invariant.

Verifies the partial unique index `uq_block_crops_current` plus the
service-layer flip ensure exactly one is_current=TRUE row per block.
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

pytestmark = [pytest.mark.integration]


def _polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
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


def _multipolygon(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    return {
        "type": "MultiPolygon",
        "coordinates": [_polygon(lon, lat, side)["coordinates"]],
    }


@pytest.mark.asyncio
async def test_assigning_new_crop_flips_previous_to_not_current(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="bc-flip",
        name="BC Flip",
        contact_email="ops@bc-flip.test",
    )

    user_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {
            "id": user_id,
            "sub": f"kc-{user_id}",
            "email": "u@bc-flip.test",
            "name": "U",
        },
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
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = build_app(ctx)

    # Look up an Egyptian crop seeded by migration 0006.
    crop_id = (
        await admin_session.execute(text("SELECT id FROM public.crops WHERE code = 'wheat'"))
    ).scalar_one()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "BCF",
                "name": "BC Flip Farm",
                "boundary": _multipolygon(31.2, 30.0),
            },
        )
        farm_id = farm_resp.json()["id"]

        block_resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _polygon(31.2, 30.0)},
        )
        block_id = block_resp.json()["id"]

        # First assignment — should be is_current=true.
        a1 = await c.post(
            f"/api/v1/blocks/{block_id}/crop-assignments",
            json={
                "crop_id": str(crop_id),
                "season_label": "2026-summer",
                "make_current": True,
            },
        )
        assert a1.status_code == 201
        assert a1.json()["is_current"] is True

        # Second assignment — should flip the prior to false.
        a2 = await c.post(
            f"/api/v1/blocks/{block_id}/crop-assignments",
            json={
                "crop_id": str(crop_id),
                "season_label": "2027-summer",
                "make_current": True,
            },
        )
        assert a2.status_code == 201
        assert a2.json()["is_current"] is True

        # Listing returns both, with exactly one is_current=true.
        listing = await c.get(f"/api/v1/blocks/{block_id}/crop-assignments")
        rows = listing.json()
        assert len(rows) == 2
        currents = [r for r in rows if r["is_current"]]
        assert len(currents) == 1
        assert currents[0]["season_label"] == "2027-summer"
