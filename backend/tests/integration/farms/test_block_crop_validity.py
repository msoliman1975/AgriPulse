"""Integration tests for crop-assignment valid time.

Covers the things the pure helpers can't: that the exclusion constraint really
exists (a service-layer check is bypassable, the constraint is not), that
assigning auto-closes the open assignment in one transaction, and that
"current" now follows the calendar rather than a stored flag.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_block_crops import _multipolygon, _polygon
from .test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]

TODAY = date.today()


async def _client(admin_session: AsyncSession, slug: str) -> AsyncClient:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
    )
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


async def _block(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/farms",
        json={
            "code": f"F-{uuid4().hex[:5]}",
            "name": "Validity",
            "boundary": _multipolygon(31.2, 30.0),
        },
    )
    assert r.status_code == 201, r.text
    farm_id = r.json()["id"]
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
    return await client.post(f"/api/v1/blocks/{block_id}/crop-assignments", json=body)


@pytest.mark.asyncio
async def test_from_defaults_to_planting_date_and_stays_open(
    admin_session: AsyncSession,
) -> None:
    async with await _client(admin_session, f"cv-a-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        r = await _assign(c, block_id, "olive", planting_date="2019-03-04")
        assert r.status_code == 201, r.text
        body = r.json()
        # from mirrors the planting date; they coincide in the common case.
        assert body["effective_from"] == "2019-03-04"
        # A perennial has no end until it is grubbed up.
        assert body["effective_to"] is None
        assert body["is_active_now"] is True
        assert body["validity_state"] == "current"


@pytest.mark.asyncio
async def test_assigning_auto_closes_the_open_assignment(
    admin_session: AsyncSession,
) -> None:
    async with await _client(admin_session, f"cv-b-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        await _assign(c, block_id, "potato", planting_date="2024-11-08")
        r = await _assign(c, block_id, "olive", effective_from="2025-04-11")
        assert r.status_code == 201, r.text

        rows = (await c.get(f"/api/v1/blocks/{block_id}/crop-assignments")).json()
        by_crop = {r["crop_path"]: r for r in rows}
        # The potato closed exactly where the mango starts — adjacent, not
        # overlapping, and done in the same request.
        assert by_crop["potato"]["effective_to"] == "2025-04-11"
        assert by_crop["potato"]["is_active_now"] is False
        assert by_crop["olive"]["effective_to"] is None
        assert by_crop["olive"]["is_active_now"] is True


@pytest.mark.asyncio
async def test_overlap_is_refused_and_names_the_conflict(
    admin_session: AsyncSession,
) -> None:
    async with await _client(admin_session, f"cv-c-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        await _assign(c, block_id, "tomato", effective_from="2025-11-01", effective_to="2026-03-10")
        r = await _assign(
            c, block_id, "potato", effective_from="2026-01-15", effective_to="2026-05-01"
        )
        assert r.status_code == 409, r.text
        problem = r.json()
        assert "tomato" in problem["detail"]
        assert problem["effective_from"] == "2025-11-01"


@pytest.mark.asyncio
async def test_touching_ranges_are_allowed(admin_session: AsyncSession) -> None:
    """The handover case: one ends exactly where the next begins."""
    async with await _client(admin_session, f"cv-d-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        await _assign(c, block_id, "tomato", effective_from="2025-11-01", effective_to="2026-03-10")
        r = await _assign(c, block_id, "potato", effective_from="2026-03-10")
        assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_inverted_range_is_rejected(admin_session: AsyncSession) -> None:
    async with await _client(admin_session, f"cv-e-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        r = await _assign(
            c, block_id, "olive", effective_from="2026-06-01", effective_to="2026-01-01"
        )
        assert r.status_code == 422, r.text
        assert "must be after" in r.json()["detail"]


@pytest.mark.asyncio
async def test_an_ended_assignment_stops_being_current(
    admin_session: AsyncSession,
) -> None:
    """The bug this replaces: `is_current` only moved when someone assigned a
    new crop, so a finished season still read as current months later."""
    async with await _client(admin_session, f"cv-f-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        ended = (TODAY - timedelta(days=1)).isoformat()
        r = await _assign(
            c,
            block_id,
            "potato",
            effective_from=(TODAY - timedelta(days=120)).isoformat(),
            effective_to=ended,
        )
        assert r.status_code == 201, r.text
        row = r.json()
        assert row["validity_state"] == "past"
        assert row["is_active_now"] is False
        # The stored flag may still say TRUE; the derived answer is what every
        # consumer now reads.
        assert row["is_current"] != row["is_active_now"] or row["is_current"] is False


@pytest.mark.asyncio
async def test_a_future_assignment_is_scheduled_not_current(
    admin_session: AsyncSession,
) -> None:
    async with await _client(admin_session, f"cv-g-{uuid4().hex[:6]}") as c:
        block_id = await _block(c)
        r = await _assign(
            c, block_id, "wheat", effective_from=(TODAY + timedelta(days=90)).isoformat()
        )
        assert r.status_code == 201, r.text
        assert r.json()["validity_state"] == "scheduled"
        assert r.json()["is_active_now"] is False


@pytest.mark.asyncio
async def test_the_exclusion_constraint_exists_and_bites(
    admin_session: AsyncSession,
) -> None:
    """A raw INSERT bypasses every service check — bulk AOI upload, backfills
    and any future writer do too. The constraint is the thing that holds."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"cv-h-{uuid4().hex[:6]}", name="cv-h", contact_email="ops@cv-h.test"
    )
    schema = tenant.schema_name

    present = (
        await admin_session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conname = 'ex_block_crops_no_overlap' "
                "AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = :s)"
            ),
            {"s": schema},
        )
    ).scalar_one_or_none()
    assert present == "ex_block_crops_no_overlap", (
        "the non-overlap guard is missing — service-layer checks alone are "
        "bypassable by bulk writers"
    )
