"""GET and PATCH /api/v1/me/notification-preferences, against live Postgres.

These are the two routes the footer of every notification email links to, so
the things pinned here are the ones a person would notice: that someone with
no preferences row sees the same defaults the fan-out would use, that turning
everything off is allowed, and that a channel the tenant has switched off says
so instead of quietly accepting the tick.

The auth middleware is stubbed the same way `test_me_flow.py` stubs it — the
routes are what is under test, not token validation.
"""

from __future__ import annotations

from uuid import UUID, uuid4

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
from app.shared.auth.context import RequestContext, TenantRole

pytestmark = [pytest.mark.integration]

URL = "/api/v1/me/notification-preferences"


class _StubAuth:
    def __init__(self, app: ASGIApp, context: RequestContext) -> None:
        self._app = app
        self._context = context

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            request.state.context = self._context
            request.state.tenant_schema = self._context.tenant_schema
        await self._app(scope, receive, send)


def _client(context: RequestContext) -> AsyncClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(iam_router)
    app.add_middleware(_StubAuth, context=context)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_user(session: AsyncSession, slug: str) -> tuple[UUID, UUID]:
    """A tenant and a member of it. Deliberately no preferences row: that is
    the common case — six of eleven production users have none."""
    tenant = await get_tenant_service(session).create_tenant(
        slug=slug,
        name=f"Tenant {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, 'Prefs User')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id, "sub": f"kc-{user_id}", "email": f"u-{user_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": uuid4(), "uid": user_id, "tid": tenant.tenant_id},
    )
    await session.commit()
    return user_id, tenant.tenant_id


def _context(user_id: UUID, tenant_id: UUID, *, email: str = "prefs@example.test"):
    return RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        email=email,
        tenant_id=tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )


@pytest.mark.asyncio
async def test_no_row_returns_the_same_defaults_the_fanout_uses(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-defaults")
    async with _client(_context(user_id, tenant_id)) as client:
        resp = await client.get(URL)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Must equal the COALESCE defaults in notifications/subscribers.py, or the
    # screen shows one thing and the sender does another.
    assert body["channels"] == ["in_app", "email"]
    assert body["language"] == "en"
    assert body["email_address"] == "prefs@example.test"


@pytest.mark.asyncio
async def test_patch_creates_the_row_and_returns_the_stored_state(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-upsert")
    async with _client(_context(user_id, tenant_id)) as client:
        resp = await client.patch(URL, json={"channels": ["in_app", "push"], "language": "ar"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["channels"] == ["in_app", "push"]
    assert resp.json()["language"] == "ar"

    row = (
        await admin_session.execute(
            text(
                "SELECT language, notification_channels FROM public.user_preferences "
                "WHERE user_id = :uid"
            ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
            {"uid": user_id},
        )
    ).one()
    assert row.language == "ar"
    assert list(row.notification_channels) == ["in_app", "push"]


@pytest.mark.asyncio
async def test_patching_one_field_leaves_the_other_alone(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-partial")
    async with _client(_context(user_id, tenant_id)) as client:
        await client.patch(URL, json={"channels": ["push"]})
        resp = await client.patch(URL, json={"language": "ar"})

    body = resp.json()
    assert body["language"] == "ar"
    # This is the whole reason the service reads before it writes.
    assert body["channels"] == ["push"]


@pytest.mark.asyncio
async def test_channels_come_back_in_display_order_without_duplicates(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-normalise")
    async with _client(_context(user_id, tenant_id)) as client:
        resp = await client.patch(URL, json={"channels": ["push", "in_app", "push"]})

    # Echoed straight back into the toggles, so a round-trip must not reshuffle.
    assert resp.json()["channels"] == ["in_app", "push"]


@pytest.mark.asyncio
async def test_switching_everything_off_is_allowed(admin_session: AsyncSession) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-silence")
    async with _client(_context(user_id, tenant_id)) as client:
        resp = await client.patch(URL, json={"channels": []})

    # A real choice, not a mistake. Nothing is lost: the work still opens in
    # the Action Center, which reads its own tables.
    assert resp.status_code == 200, resp.text
    assert resp.json()["channels"] == []


@pytest.mark.asyncio
async def test_webhook_is_refused_because_it_is_not_a_per_user_channel(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-webhook")
    async with _client(_context(user_id, tenant_id)) as client:
        resp = await client.patch(URL, json={"channels": ["in_app", "webhook"]})

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "webhook" in detail
    assert "per tenant" in detail


@pytest.mark.asyncio
async def test_a_channel_the_tenant_switched_off_reports_why(
    admin_session: AsyncSession,
) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-tenant-off")
    await admin_session.execute(
        text(
            "UPDATE public.tenant_settings "
            "SET alert_notification_channels = ARRAY['in_app']::text[] "
            "WHERE tenant_id = :tid"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tenant_id},
    )
    await admin_session.commit()

    async with _client(_context(user_id, tenant_id)) as client:
        body = (await client.get(URL)).json()

    states = {a["channel"]: a for a in body["availability"]}
    assert states["in_app"]["deliverable"] is True
    assert states["email"]["deliverable"] is False
    assert states["email"]["reason"] == "tenant_disabled"
    assert body["tenant_channels"] == ["in_app"]
    # The person's own choice is untouched by the tenant switch — it starts
    # working again the day an admin turns the channel back on.
    assert "email" in body["channels"]


@pytest.mark.asyncio
async def test_an_account_with_no_address_says_so(admin_session: AsyncSession) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-no-email")
    async with _client(_context(user_id, tenant_id, email="")) as client:
        body = (await client.get(URL)).json()

    states = {a["channel"]: a for a in body["availability"]}
    assert body["email_address"] is None
    assert states["email"]["deliverable"] is False
    assert states["email"]["reason"] == "no_email_address"


@pytest.mark.asyncio
async def test_push_reports_no_registered_device(admin_session: AsyncSession) -> None:
    user_id, tenant_id = await _make_user(admin_session, "prefs-no-device")
    # A tenant's `alert_notification_channels` defaults to in_app + email, so
    # push has to be enabled here or the tenant switch answers first — which
    # is the documented precedence, and what the next test pins.
    await admin_session.execute(
        text(
            "UPDATE public.tenant_settings "
            "SET alert_notification_channels = ARRAY['in_app','email','push']::text[] "
            "WHERE tenant_id = :tid"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tenant_id},
    )
    await admin_session.commit()

    async with _client(_context(user_id, tenant_id)) as client:
        body = (await client.get(URL)).json()

    states = {a["channel"]: a for a in body["availability"]}
    assert body["registered_device_count"] == 0
    assert states["push"]["deliverable"] is False
    assert states["push"]["reason"] == "no_registered_device"


@pytest.mark.asyncio
async def test_a_platform_admin_without_a_tenant_can_still_read_their_own(
    admin_session: AsyncSession,
) -> None:
    # No tenant claim, so no tenant channel list and no device table to read.
    # Refusing here would lock a Platform Admin out of their own settings.
    user_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, 'No Tenant')"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id, "sub": f"kc-{user_id}", "email": f"nt-{user_id}@example.test"},
    )
    await admin_session.commit()

    context = RequestContext(
        user_id=user_id,
        keycloak_subject=f"kc-{user_id}",
        email="admin@example.test",
        tenant_id=None,
    )
    async with _client(context) as client:
        resp = await client.get(URL)

    assert resp.status_code == 200, resp.text
    assert resp.json()["channels"] == ["in_app", "email"]


@pytest.mark.asyncio
async def test_the_tenant_switch_is_reported_before_the_missing_device(
    admin_session: AsyncSession,
) -> None:
    """Push is off for a new tenant, and that is the reason the person sees.

    `alert_notification_channels` defaults to in_app + email, so push is
    switched off for every tenant until an administrator adds it. Reporting
    "no phone signed in" there would send someone to install an app that
    still would not receive anything.
    """
    user_id, tenant_id = await _make_user(admin_session, "prefs-precedence")
    async with _client(_context(user_id, tenant_id)) as client:
        body = (await client.get(URL)).json()

    states = {a["channel"]: a for a in body["availability"]}
    assert body["registered_device_count"] == 0
    assert states["push"]["reason"] == "tenant_disabled"
