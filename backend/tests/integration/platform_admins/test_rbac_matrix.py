"""Integration tests for GET /api/v1/admin/rbac/matrix.

The interesting part is the holder-count query: it unions three tables in the
`public` schema and must count *people*, not assignment rows. A FarmManager
scoped to five farms is one person, and a revoked or soft-deleted assignment
is nobody.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.shared.auth.context import PlatformRole, TenantRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]


def _client(context) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=build_app(context)), base_url="http://test")


def _platform_client() -> AsyncClient:
    return _client(
        make_context(user_id=uuid4(), tenant_id=None, platform_role=PlatformRole.PLATFORM_ADMIN)
    )


async def _seed_user(session, email: str) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ),
        {"id": user_id, "sub": f"kc-{user_id}", "email": email, "name": email},
    )
    return user_id


@pytest.mark.asyncio
async def test_tenant_role_cannot_read_the_matrix() -> None:
    context = make_context(user_id=uuid4(), tenant_id=uuid4(), tenant_role=TenantRole.TENANT_OWNER)
    async with _client(context) as client:
        response = await client.get("/api/v1/admin/rbac/matrix")
    assert response.status_code == 403
    # RFC 7807: the capability rides in the problem document so support can
    # tell "wrong role" apart from "route is down" without reading pod logs.
    assert "platform.read" in response.text


@pytest.mark.asyncio
async def test_matrix_describes_every_role_and_capability() -> None:
    async with _platform_client() as client:
        response = await client.get("/api/v1/admin/rbac/matrix")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["capability_count"] == len(body["capabilities"])
    assert body["active_count"] + body["stub_count"] == body["capability_count"]

    names = {r["name"] for r in body["roles"]}
    assert {"PlatformAdmin", "TenantOwner", "BillingAdmin", "Scout", "Viewer"} <= names

    tiers = {r["name"]: r["tier"] for r in body["roles"]}
    assert tiers["PlatformAdmin"] == "platform"
    assert tiers["BillingAdmin"] == "tenant"
    assert tiers["Scout"] == "farm"

    for cap in body["capabilities"]:
        assert cap["scope"] in {"platform", "tenant", "farm"}
        assert cap["status"] in {"active", "stub"}
        # Split server-side so the UI never re-derives it from the name.
        assert cap["name"] == f"{cap['resource']}.{cap['action']}"


@pytest.mark.asyncio
async def test_wildcard_role_is_expanded_but_flagged() -> None:
    async with _platform_client() as client:
        body = (await client.get("/api/v1/admin/rbac/matrix")).json()

    roles = {r["name"]: r for r in body["roles"]}
    admin = roles["PlatformAdmin"]
    assert admin["wildcard"] is True
    # "*" must never reach the client — it would need special-casing in every
    # filter and count on the page.
    assert "*" not in admin["capabilities"]
    assert admin["capability_count"] == body["capability_count"]

    viewer = roles["Viewer"]
    assert viewer["wildcard"] is False
    assert 0 < viewer["capability_count"] < body["capability_count"]


@pytest.mark.asyncio
async def test_holder_counts_count_people_not_assignments(admin_session) -> None:
    session = admin_session
    tenant_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.tenants "
            "(id, name, slug, schema_name, status, contact_email) "
            "VALUES (:id, 'RBAC Count Co', :slug, :schema, 'active', :email)"
        ),
        {
            "id": tenant_id,
            "slug": f"rbac-{tenant_id.hex[:8]}",
            "schema": f"tenant_{tenant_id.hex}",
            "email": f"rbac-{tenant_id.hex[:8]}@example.com",
        },
    )

    counted = await _seed_user(session, f"counted-{uuid4().hex[:8]}@example.com")
    revoked = await _seed_user(session, f"revoked-{uuid4().hex[:8]}@example.com")

    membership_ids = {}
    for user_id in (counted, revoked):
        membership_id = uuid4()
        membership_ids[user_id] = membership_id
        await session.execute(
            text(
                "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
                "VALUES (:id, :uid, :tid, 'active')"
            ),
            {"id": membership_id, "uid": user_id, "tid": tenant_id},
        )

    # One person, three farm scopes of the same role -> must count once.
    for _ in range(3):
        await session.execute(
            text(
                "INSERT INTO public.farm_scopes (id, membership_id, farm_id, role) "
                "VALUES (:id, :mid, :fid, 'Agronomist')"
            ),
            {"id": uuid4(), "mid": membership_ids[counted], "fid": uuid4()},
        )
    # A revoked scope is nobody.
    await session.execute(
        text(
            "INSERT INTO public.farm_scopes (id, membership_id, farm_id, role, revoked_at) "
            "VALUES (:id, :mid, :fid, 'Agronomist', now())"
        ),
        {"id": uuid4(), "mid": membership_ids[revoked], "fid": uuid4()},
    )
    await session.commit()

    try:
        async with _platform_client() as client:
            body = (await client.get("/api/v1/admin/rbac/matrix")).json()
        agronomist = {r["name"]: r for r in body["roles"]}["Agronomist"]
        assert agronomist["holders"]["farm"] >= 1
        assert agronomist["holders"]["total"] == agronomist["holders"]["farm"]

        rows = (
            await session.execute(
                text(
                    "SELECT count(DISTINCT m.user_id) AS n FROM public.farm_scopes fs "
                    "JOIN public.tenant_memberships m ON m.id = fs.membership_id "
                    "WHERE fs.role = 'Agronomist' AND fs.revoked_at IS NULL "
                    "AND m.deleted_at IS NULL AND m.status = 'active'"
                )
            )
        ).one()
        assert agronomist["holders"]["farm"] == rows.n
    finally:
        await session.execute(text("DELETE FROM public.tenants WHERE id = :id"), {"id": tenant_id})
        await session.execute(
            text("DELETE FROM public.users WHERE id = ANY(:ids)"),
            {"ids": [counted, revoked]},
        )
        await session.commit()
