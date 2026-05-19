"""Integration test: GET /api/v1/me end-to-end against a live Postgres.

Auth is *not* exercised here — we mount the iam router on a minimal app
that pre-populates `request.state.context` so the route runs as if the
JWT had already been validated. Real Keycloak token validation is
covered by a separate Keycloak-container test in a later prompt.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import install_exception_handlers
from app.modules.iam.router import router as iam_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import (
    FarmRole,
    FarmScope,
    PlatformRole,
    RequestContext,
    TenantRole,
)

pytestmark = [pytest.mark.integration]


class _StubAuth:
    """Tiny ASGI middleware: stamp a fixed RequestContext on request.state."""

    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def _build_app(context: RequestContext) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(iam_router)
    app.add_middleware(_StubAuth, context=context)
    return app


@pytest.mark.asyncio
async def test_me_returns_profile_preferences_memberships_scopes(
    admin_session: AsyncSession,
) -> None:
    # Create a tenant, a user, link them, grant a tenant role + a farm scope.
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="me-flow-test",
        name="Me Flow Tenant",
        contact_email="ops@me-flow.test",
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
            "email": f"u-{user_id}@example.test",
            "name": "Test User",
        },
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.user_preferences (user_id, language, unit_system) "
            "VALUES (:id, 'ar', 'acre')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id},
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
    farm_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.farm_scopes (membership_id, farm_id, role) "
            "VALUES (:mid, :fid, 'FarmManager')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "fid": farm_id},
    )
    await admin_session.commit()

    context = RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
        farm_scopes=(FarmScope(farm_id=farm_id, role=FarmRole.FARM_MANAGER),),
    )

    app = _build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/me")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(user_id)
    assert body["full_name"] == "Test User"
    assert body["preferences"]["language"] == "ar"
    assert body["preferences"]["unit_system"] == "acre"

    memberships = body["tenant_memberships"]
    assert len(memberships) == 1
    assert memberships[0]["tenant_slug"] == "me-flow-test"
    assert any(r["role"] == "TenantAdmin" for r in memberships[0]["tenant_roles"])

    scopes = body["farm_scopes"]
    assert len(scopes) == 1
    assert scopes[0]["farm_id"] == str(farm_id)
    assert scopes[0]["role"] == "FarmManager"


@pytest.mark.asyncio
async def test_me_upserts_user_for_first_login(admin_session: AsyncSession) -> None:
    """Phase-2 sync handler: a valid JWT for a user not yet in
    `public.users` auto-creates the row on first /me call instead of
    returning 404 (the old behavior). The upsert is keyed on the JWT
    `sub` so re-issued tokens still find the row."""
    sub = uuid4()
    context = RequestContext(
        user_id=sub,
        keycloak_subject=str(sub),
        email=f"first-login-{sub}@example.test",
        full_name="First Login User",
        tenant_id=None,
        platform_role=PlatformRole.PLATFORM_ADMIN,
    )
    app = _build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(sub)
    assert body["email"] == f"first-login-{sub}@example.test"
    assert body["full_name"] == "First Login User"

    # Row really did land in the DB — not just an in-memory MeResponse.
    row = (
        await admin_session.execute(
            text("SELECT email, keycloak_subject FROM public.users WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": sub},
        )
    ).one()
    assert row.keycloak_subject == str(sub)


@pytest.mark.asyncio
async def test_me_rekeys_user_when_keycloak_sub_changes(admin_session: AsyncSession) -> None:
    """When the same email exists but the JWT carries a new sub
    (Keycloak user delete+recreate), the upsert handler re-keys the
    public.users row to the new sub. ON UPDATE CASCADE (migration 0023)
    moves tenant_memberships + role assignments to the new id so the
    user keeps their access. This is the scenario that originally
    surfaced today's bug — see fix/iam-jwt-sync."""
    old_id = uuid4()
    new_sub = uuid4()
    email = f"recreated-{new_sub}@example.test"

    # Seed: old row + a tenant membership pointing at it.
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"rekey-{new_sub.hex[:10]}",
        name="Rekey Test Tenant",
        contact_email="ops@rekey.test",
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, 'Old Name')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": old_id, "sub": f"kc-old-{old_id}", "email": email},
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
        {"mid": membership_id, "uid": old_id, "tid": tenant.tenant_id},
    )
    await admin_session.commit()

    # New JWT carries new_sub but same email.
    context = RequestContext(
        user_id=new_sub,
        keycloak_subject=str(new_sub),
        email=email,
        full_name="New Display Name",
        tenant_id=tenant.tenant_id,
    )
    app = _build_app(context)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/me")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(new_sub)

    # The old id is gone; the membership now references new_sub
    # courtesy of the ON UPDATE CASCADE.
    remaining_old = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.users WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": old_id},
        )
    ).scalar_one()
    assert remaining_old == 0
    memb_user_id = (
        await admin_session.execute(
            text("SELECT user_id FROM public.tenant_memberships WHERE id = :id").bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True))
            ),
            {"id": membership_id},
        )
    ).scalar_one()
    assert memb_user_id == new_sub
