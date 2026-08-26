"""The Arabic name round-trips on a farm and on a block.

Tenant migration 0087 added `name_ar` (and `description_ar` on farms). These
tests cover the three things that can break independently: the create body
reaching the INSERT, the read projection returning the column, and the PATCH
allowlist accepting the key. The allowlist is the one worth pinning — a key
missing from `_FARM_UPDATABLE_COLUMNS` raises a 500 rather than ignoring the
field, and a key present but absent from the read projection returns a 200
with the old value, which reads as "the save did nothing".
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]

FARM_AR = "مزرعة النور"  # "Al Nour farm"
FARM_AR_2 = "مزرعة الأمل"  # "Al Amal farm"
BLOCK_AR = "القطعة الأولى"  # "Block one"


async def _tenant_app(admin_session: AsyncSession, slug: str):
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=slug,
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return build_app(context)


@pytest.mark.asyncio
async def test_farm_arabic_name_round_trips(admin_session: AsyncSession) -> None:
    app = await _tenant_app(admin_session, "ar-names-farm")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={
                "code": "FARM-AR",
                "name": "Al Nour Farm",
                "name_ar": FARM_AR,
                "description": "Mango, north block",
                "description_ar": "مانجو",
                "boundary": _square(31.2, 30.0),
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name_ar"] == FARM_AR
        assert body["description_ar"] == "مانجو"
        farm_id = body["id"]

        # Read back on its own, not from the create response.
        resp = await c.get(f"/api/v1/farms/{farm_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["name_ar"] == FARM_AR

        # And on the list projection, which selects its own column set.
        resp = await c.get("/api/v1/farms")
        assert resp.status_code == 200, resp.text
        rows = {r["id"]: r for r in resp.json()["items"]}
        assert rows[farm_id]["name_ar"] == FARM_AR

        resp = await c.patch(f"/api/v1/farms/{farm_id}", json={"name_ar": FARM_AR_2})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name_ar"] == FARM_AR_2
        # The English name is untouched by an Arabic-only edit.
        assert resp.json()["name"] == "Al Nour Farm"


@pytest.mark.asyncio
async def test_farm_without_arabic_name_reads_null(admin_session: AsyncSession) -> None:
    """Omitting the field stores NULL rather than an empty string.

    Every reader falls back with `COALESCE(NULLIF(name_ar, ''), name)`, so an
    empty string would render a blank name instead of the English one.
    """
    app = await _tenant_app(admin_session, "ar-names-farm-none")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={"code": "FARM-EN", "name": "English Only", "boundary": _square(31.3, 30.1)},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["name_ar"] is None


@pytest.mark.asyncio
async def test_block_arabic_name_round_trips(admin_session: AsyncSession) -> None:
    app = await _tenant_app(admin_session, "ar-names-block")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={"code": "FARM-B", "name": "Block Host", "boundary": _square(31.2, 30.0)},
        )
        assert resp.status_code == 201, resp.text
        farm_id = resp.json()["id"]

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B-1",
                "name": "Block One",
                "name_ar": BLOCK_AR,
                "boundary": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [31.2, 30.0],
                            [31.201, 30.0],
                            [31.201, 30.001],
                            [31.2, 30.001],
                            [31.2, 30.0],
                        ]
                    ],
                },
            },
        )
        assert resp.status_code == 201, resp.text
        block = resp.json()
        assert block["name_ar"] == BLOCK_AR
        block_id = block["id"]

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks")
        assert resp.status_code == 200, resp.text
        rows = {r["id"]: r for r in resp.json()["items"]}
        assert rows[block_id]["name_ar"] == BLOCK_AR

        resp = await c.patch(f"/api/v1/blocks/{block_id}", json={"name_ar": "قطعة 2"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name_ar"] == "قطعة 2"
