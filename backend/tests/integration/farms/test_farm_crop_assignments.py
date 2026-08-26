"""Integration tests for `GET /v1/farms/{farm_id}/crop-assignments`.

The route exists for one caller: the Farm Console map label, which can be
scrubbed back to a scene from a past season. So the thing under test is the
date parameter — that the answer follows the assignment's validity range and
not a stored "current" flag.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_block_crops import _multipolygon, _polygon
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


async def _client(admin_session: AsyncSession, slug: str) -> AsyncClient:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _farm(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/farms",
        json={
            "code": f"F-{uuid4().hex[:5]}",
            "name": "Crop labels",
            "boundary": _multipolygon(31.2, 30.0),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _block(client: AsyncClient, farm_id: str) -> str:
    r = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={"code": f"B-{uuid4().hex[:5]}", "boundary": _polygon(31.2, 30.0)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _crop_id(client: AsyncClient, code: str) -> str:
    crops = await client.get("/api/v1/crops")
    return next(c["id"] for c in crops.json() if c["code"] == code)


async def _assign(client: AsyncClient, block_id: str, crop: str, **kw):
    body = {"crop_id": await _crop_id(client, crop), "season_label": "2026", **kw}
    r = await client.post(f"/api/v1/blocks/{block_id}/crop-assignments", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_returns_one_row_per_block_with_the_crop_name(
    admin_session: AsyncSession,
) -> None:
    async with await _client(admin_session, f"fca-a-{uuid4().hex[:6]}") as c:
        farm_id = await _farm(c)
        block_id = await _block(c, farm_id)
        await _assign(c, block_id, "olive", planting_date="2019-03-04")

        r = await c.get(f"/api/v1/farms/{farm_id}/crop-assignments")
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["block_id"] == block_id
        assert row["crop_path"] == "olive"
        # Both languages ship, so a locale switch needs no refetch.
        assert row["crop_name_en"]
        assert row["crop_name_ar"]


@pytest.mark.asyncio
async def test_a_block_with_no_assignment_is_omitted(admin_session: AsyncSession) -> None:
    async with await _client(admin_session, f"fca-b-{uuid4().hex[:6]}") as c:
        farm_id = await _farm(c)
        planted = await _block(c, farm_id)
        bare = await _block(c, farm_id)
        await _assign(c, planted, "olive", planting_date="2019-03-04")

        r = await c.get(f"/api/v1/farms/{farm_id}/crop-assignments")
        assert r.status_code == 200, r.text
        block_ids = {row["block_id"] for row in r.json()}
        assert block_ids == {planted}
        assert bare not in block_ids


@pytest.mark.asyncio
async def test_on_a_past_date_returns_the_crop_of_that_season(
    admin_session: AsyncSession,
) -> None:
    """The whole reason the route takes a date.

    Two seasons on one block: assigning the second auto-closes the first at
    the second's `effective_from`. Asking for a date inside the first range
    must name the first crop, not today's.
    """
    async with await _client(admin_session, f"fca-c-{uuid4().hex[:6]}") as c:
        farm_id = await _farm(c)
        block_id = await _block(c, farm_id)
        await _assign(c, block_id, "wheat", effective_from="2024-01-01")
        await _assign(c, block_id, "maize", effective_from="2025-06-01")

        past = await c.get(f"/api/v1/farms/{farm_id}/crop-assignments", params={"on": "2024-05-01"})
        assert past.status_code == 200, past.text
        assert [row["crop_path"] for row in past.json()] == ["wheat"]

        now = await c.get(
            f"/api/v1/farms/{farm_id}/crop-assignments", params={"on": date.today().isoformat()}
        )
        assert now.status_code == 200, now.text
        assert [row["crop_path"] for row in now.json()] == ["maize"]


@pytest.mark.asyncio
async def test_before_any_assignment_returns_nothing(admin_session: AsyncSession) -> None:
    async with await _client(admin_session, f"fca-d-{uuid4().hex[:6]}") as c:
        farm_id = await _farm(c)
        block_id = await _block(c, farm_id)
        await _assign(c, block_id, "wheat", effective_from="2024-01-01")

        r = await c.get(f"/api/v1/farms/{farm_id}/crop-assignments", params={"on": "2023-01-01"})
        assert r.status_code == 200, r.text
        assert r.json() == []


@pytest.mark.asyncio
async def test_unknown_farm_is_not_found(admin_session: AsyncSession) -> None:
    async with await _client(admin_session, f"fca-e-{uuid4().hex[:6]}") as c:
        r = await c.get(f"/api/v1/farms/{uuid4()}/crop-assignments")
        assert r.status_code == 404, r.text
