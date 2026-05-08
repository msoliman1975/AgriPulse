"""HTTP roundtrip for the inbox endpoints — list, unread-count, transition."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.notifications.router import router as notifications_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


async def _seed_inbox_row(
    admin: AsyncSession,
    *,
    schema: str,
    user_id,
    title: str = "test",
    body: str = "test body",
):
    item_id = uuid4()
    await admin.execute(
        text(
            f'INSERT INTO "{schema}".in_app_inbox '
            "(id, user_id, severity, title, body, link_url) "
            "VALUES (:id, :uid, 'critical', :title, :body, '/alerts/x?alert=y')"
        ).bindparams(
            bindparam("id", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
        ),
        {"id": item_id, "uid": user_id, "title": title, "body": body},
    )
    await admin.commit()
    return item_id


@pytest.mark.asyncio
async def test_inbox_list_unread_count_and_transitions(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4b-endpoints",
        name="PR-S4-B endpoints",
        contact_email="ops@pr-s4b-ep.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    item_a = await _seed_inbox_row(
        admin_session, schema=tenant.schema_name, user_id=user_id, title="alpha"
    )
    item_b = await _seed_inbox_row(
        admin_session, schema=tenant.schema_name, user_id=user_id, title="bravo"
    )

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(notifications_router)
    app.add_middleware(StubAuth, context=context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # List
        listed = await client.get("/api/v1/inbox")
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        titles = sorted(r["title"] for r in rows)
        assert titles == ["alpha", "bravo"]

        # Unread count
        count = await client.get("/api/v1/inbox/unread-count")
        assert count.status_code == 200, count.text
        assert count.json()["count"] == 2

        # Mark item_a read
        marked = await client.patch(f"/api/v1/inbox/{item_a}", json={"action": "read"})
        assert marked.status_code == 200, marked.text
        assert marked.json()["read_at"] is not None

        # Unread count drops
        count2 = await client.get("/api/v1/inbox/unread-count")
        assert count2.json()["count"] == 1

        # Archive item_b
        archived = await client.patch(f"/api/v1/inbox/{item_b}", json={"action": "archive"})
        assert archived.status_code == 200
        assert archived.json()["archived_at"] is not None

        # Default list excludes archived
        default = await client.get("/api/v1/inbox")
        assert {r["title"] for r in default.json()} == {"alpha"}

        # include_archived=true brings it back
        with_archived = await client.get("/api/v1/inbox?include_archived=true")
        assert {r["title"] for r in with_archived.json()} == {"alpha", "bravo"}


@pytest.mark.asyncio
async def test_inbox_patch_unknown_item_404(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4b-404",
        name="PR-S4-B 404",
        contact_email="ops@pr-s4b-404.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(notifications_router)
    app.add_middleware(StubAuth, context=context)

    bogus = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(f"/api/v1/inbox/{bogus}", json={"action": "read"})
        assert resp.status_code == 404
