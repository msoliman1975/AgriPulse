"""The farm's health override, end to end through the route.

Health is a resolution tier, not a template, so the surface is two routes
and no more: GET and PUT. The tests that matter are the ones proving the
absences — no apply, no apply-preview, and a lock that needs no divergence
modal because nothing can be out of step with it.

The unit tests around this cover the merge rule and the schema. What only a
real database can show is that the column exists with the CHECK 0089 adds,
that `extra="forbid"` and `parse_definition` both fire on the wire, and that
the capability check does not deny a farm-scoped user.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context

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


async def _create_user(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> None:
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


async def _bootstrap(admin_session: AsyncSession, slug: str):
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, context


@pytest.fixture(autouse=True)
def _enable_feature_flag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FARM_CONFIG_TEMPLATE_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _farm(c: AsyncClient) -> str:
    farm = await c.post(
        "/api/v1/farms",
        json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
    )
    return str(farm.json()["id"])


@pytest.mark.asyncio
async def test_round_trip_stores_only_what_was_sent(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "health-tpl-crud")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)

        initial = await c.get(f"/api/v1/farms/{farm_id}/config/health/template")
        assert initial.status_code == 200
        assert initial.json() == {"definition": None, "locked": False}

        put = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"stale_after_hours": 12}},
        )
        assert put.status_code == 200
        # One key in, one key stored. Not seven with six at today's defaults
        # — that would pin them and stop the farm tracking the knowledge base.
        assert put.json()["definition"] == {"stale_after_hours": 12}

        again = await c.get(f"/api/v1/farms/{farm_id}/config/health/template")
        assert again.json()["definition"] == {"stale_after_hours": 12}


@pytest.mark.asyncio
async def test_a_null_that_was_sent_is_kept_and_the_rest_is_not(
    admin_session: AsyncSession,
) -> None:
    """`snoozed_as: null` is a real value — "count a snoozed alert by its own
    severity" — and must survive, while the six fields nobody sent must not
    appear at all."""
    _, context = await _bootstrap(admin_session, "health-tpl-null")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        put = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"snoozed_as": None}},
        )
        assert put.status_code == 200
        assert put.json()["definition"] == {"snoozed_as": None}


@pytest.mark.asyncio
async def test_clearing_stores_null_not_an_empty_object(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "health-tpl-clear")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"stale_after_hours": 12}},
        )
        cleared = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": None},
        )
        assert cleared.status_code == 200
        # NULL says "this farm follows the knowledge base". `{}` would say
        # "this farm has decided", and the two must not be confused.
        assert cleared.json()["definition"] is None


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_at_the_boundary(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "health-tpl-unknown")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        resp = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"stale_hours": 12}},
        )
        # `extra="forbid"` on the body schema. A dropped key would mean the
        # tier below it for ever, with the farm believing it had been saved.
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_value_outside_the_bounded_set_is_refused(admin_session: AsyncSession) -> None:
    """The second gate. The key is known, so the schema lets it through and
    `parse_definition` has to catch it before the write."""
    _, context = await _bootstrap(admin_session, "health-tpl-bounds")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        resp = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"no_tree_coverage": "critical"}},
        )
        assert resp.status_code in (400, 422)

        after = await c.get(f"/api/v1/farms/{farm_id}/config/health/template")
        assert after.json()["definition"] is None


@pytest.mark.asyncio
async def test_health_appears_in_the_lock_state(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "health-tpl-locks")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        locks = await c.get(f"/api/v1/farms/{farm_id}/config/locks")
        assert locks.status_code == 200
        assert locks.json()["health"] is False


@pytest.mark.asyncio
async def test_locking_health_needs_no_divergence_confirmation(
    admin_session: AsyncSession,
) -> None:
    """Every other category can raise LockDivergenceError and demand a
    "lock and overwrite" confirmation. Health cannot: there is no block-side
    copy, so nothing can be out of step with it."""
    _, context = await _bootstrap(admin_session, "health-tpl-lock")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        lock = await c.post(f"/api/v1/farms/{farm_id}/config/health/lock", json={})
        assert lock.status_code == 200
        assert lock.json()["locked"] is True

        locks = await c.get(f"/api/v1/farms/{farm_id}/config/locks")
        assert locks.json()["health"] is True


@pytest.mark.asyncio
async def test_a_locked_farm_refuses_the_edit_until_it_is_unlocked(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "health-tpl-locked-put")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        await c.post(f"/api/v1/farms/{farm_id}/config/health/lock", json={})

        blocked = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"stale_after_hours": 12}},
        )
        assert blocked.status_code == 409

        await c.post(f"/api/v1/farms/{farm_id}/config/health/unlock", json={})
        allowed = await c.put(
            f"/api/v1/farms/{farm_id}/config/health/template",
            json={"definition": {"stale_after_hours": 12}},
        )
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_there_is_no_apply_and_no_preview(admin_session: AsyncSession) -> None:
    """The absence is the design. An Apply would copy a resolved answer into
    blocks and start it drifting from the tiers it came from — the exact
    failure this project exists to end."""
    _, context = await _bootstrap(admin_session, "health-tpl-no-apply")
    app = build_app(context, with_config=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id = await _farm(c)
        for path in ("apply", "apply-preview"):
            resp = await c.post(f"/api/v1/farms/{farm_id}/config/health/{path}", json={})
            assert resp.status_code == 404, path
