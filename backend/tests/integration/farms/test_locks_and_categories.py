"""Integration tests for PR-3: locks + irrigation + org templates.

Covers the four scenarios from the proposal:

  * Lock-on with divergence returns 409 + diff.
  * force_overwrite=true resolves divergence and sets the lock.
  * Lock-on then attempt block edit returns 409.
  * Lock-off allows block edits again.
  * Org-tags merge is additive — farm tags get added without removing
    block-local tags.
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


def _square_polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
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
    tenant = await tenancy.create_tenant(
        slug=slug, name=slug, contact_email=f"ops@{slug}.test"
    )
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


# ---- Tests ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_irrigation_lock_with_divergence_returns_409_then_force_succeeds(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "lk-irrdiv")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B1",
                "boundary": _square_polygon(31.21, 30.001),
                "irrigation_system": "drip",
            },
        )
        block_id = block.json()["id"]

        # Set the template to "pivot"; block is "drip" → divergent.
        await c.put(
            f"/api/v1/farms/{farm_id}/config/irrigation/template",
            json={
                "irrigation_system": "pivot",
                "irrigation_source": None,
                "flow_rate_m3_per_hour": None,
            },
        )

        # Lock-without-force should 409.
        denied = await c.post(
            f"/api/v1/farms/{farm_id}/config/irrigation/lock",
            json={"force_overwrite": False},
        )
        assert denied.status_code == 409
        assert "diff" in denied.json()

        # Force path: Apply runs, then the lock is set.
        forced = await c.post(
            f"/api/v1/farms/{farm_id}/config/irrigation/lock",
            json={"force_overwrite": True},
        )
        assert forced.status_code == 200
        assert forced.json()["locked"] is True

        # Confirm the block now matches.
        row = (
            await admin_session.execute(
                text(
                    "SELECT irrigation_system FROM blocks WHERE id = :id"
                ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                {"id": UUID(block_id)},
            )
        ).first()
        assert row.irrigation_system == "pivot"


@pytest.mark.asyncio
async def test_locked_block_irrigation_edit_returns_409(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "lk-irrblock")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B", "boundary": _square_polygon(31.21, 30.001)},
        )
        block_id = block.json()["id"]

        # Lock irrigation (no template + no blocks divergent → trivially OK).
        await c.put(
            f"/api/v1/farms/{farm_id}/config/irrigation/template",
            json={
                "irrigation_system": None,
                "irrigation_source": None,
                "flow_rate_m3_per_hour": None,
            },
        )
        locked = await c.post(
            f"/api/v1/farms/{farm_id}/config/irrigation/lock",
            json={"force_overwrite": False},
        )
        assert locked.status_code == 200

        # Block PATCH that touches irrigation_system → 409.
        denied = await c.patch(
            f"/api/v1/blocks/{block_id}",
            json={"irrigation_system": "pivot"},
        )
        assert denied.status_code == 409


@pytest.mark.asyncio
async def test_unlock_restores_block_edits(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "lk-unlock")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B", "boundary": _square_polygon(31.21, 30.001)},
        )
        block_id = block.json()["id"]

        # Lock then unlock.
        await c.put(
            f"/api/v1/farms/{farm_id}/config/irrigation/template",
            json={
                "irrigation_system": None,
                "irrigation_source": None,
                "flow_rate_m3_per_hour": None,
            },
        )
        await c.post(
            f"/api/v1/farms/{farm_id}/config/irrigation/lock",
            json={"force_overwrite": False},
        )
        await c.post(f"/api/v1/farms/{farm_id}/config/irrigation/unlock")

        # Block PATCH works again.
        ok = await c.patch(
            f"/api/v1/blocks/{block_id}",
            json={"irrigation_system": "drip"},
        )
        assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_org_apply_is_additive(admin_session: AsyncSession) -> None:
    """Block keeps its local tags; farm template tags are merged in."""
    _, context = await _bootstrap(admin_session, "lk-orgmerge")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B",
                "boundary": _square_polygon(31.21, 30.001),
                "tags": ["#south"],
            },
        )
        block_id = block.json()["id"]

        await c.put(
            f"/api/v1/farms/{farm_id}/config/org/template",
            json={"default_tags": ["#cotton"]},
        )
        applied = await c.post(
            f"/api/v1/farms/{farm_id}/config/org/apply",
            json={"block_ids": None},
        )
        assert applied.status_code == 200
        assert applied.json()["blocks_touched"] == 1

        # Verify the block has BOTH tags.
        row = (
            await admin_session.execute(
                text("SELECT tags FROM blocks WHERE id = :id").bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True))
                ),
                {"id": UUID(block_id)},
            )
        ).first()
        tags = set(row.tags or [])
        assert "#south" in tags
        assert "#cotton" in tags


@pytest.mark.asyncio
async def test_locked_org_blocks_tag_edits(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "lk-orgblock")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B", "boundary": _square_polygon(31.21, 30.001)},
        )
        block_id = block.json()["id"]

        await c.put(
            f"/api/v1/farms/{farm_id}/config/org/template",
            json={"default_tags": []},
        )
        locked = await c.post(
            f"/api/v1/farms/{farm_id}/config/org/lock",
            json={"force_overwrite": False},
        )
        assert locked.status_code == 200

        denied = await c.patch(
            f"/api/v1/blocks/{block_id}",
            json={"tags": ["#south"]},
        )
        assert denied.status_code == 409


@pytest.mark.asyncio
async def test_get_lock_state(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "lk-state")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        resp = await c.get(f"/api/v1/farms/{farm_id}/config/locks")
        assert resp.status_code == 200
        assert resp.json() == {
            "subscriptions": False,
            "irrigation": False,
            "org": False,
        }
