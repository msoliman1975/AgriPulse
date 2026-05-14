"""Integration tests for the block/farm inactivation lifecycle.

Covers the schema-level invariants and the cross-module cascade
introduced in tenant migration 0026 / farms PR-1.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4


def _today_utc() -> date:
    """Match the server's UTC ``current_date`` semantics."""
    return datetime.now(UTC).date()


import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _create_user_in_tenant(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> None:
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
    return tenant, context


@pytest.mark.asyncio
async def test_create_farm_emits_active_window(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "life-create")
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/api/v1/farms",
            json={"code": "F1", "name": "F1", "boundary": _square(31.2, 30.0)},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active_from"] == _today_utc().isoformat()
    assert body["active_to"] is None
    assert body["is_active"] is True
    assert "status" not in body


@pytest.mark.asyncio
async def test_create_block_with_future_active_from_is_inactive(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "life-future")
    app = build_app(context)

    future = (_today_utc() + timedelta(days=10)).isoformat()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        assert farm.status_code == 201
        block = await c.post(
            f"/api/v1/farms/{farm.json()['id']}/blocks",
            json={
                "code": "B1",
                "boundary": _square_polygon(31.201, 30.001),
                "active_from": future,
            },
        )
    assert block.status_code == 201, block.text
    body = block.json()
    assert body["active_from"] == future
    assert body["is_active"] is False


@pytest.mark.asyncio
async def test_inactivate_preview_then_inactivate(
    admin_session: AsyncSession,
) -> None:
    tenant, context = await _bootstrap(admin_session, "life-inact")
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _square_polygon(31.201, 30.001)},
        )
        block_id = block.json()["id"]

    # Seed an open alert + a future-pending irrigation schedule + a
    # future-scheduled plan activity + an active imagery subscription
    # for this block so the cascade has things to count.
    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    await admin_session.execute(
        text(
            """
            INSERT INTO alerts (id, block_id, rule_code, severity, status,
                                signal_snapshot, created_at, updated_at)
            VALUES (gen_random_uuid(), :bid, 'r.test', 'warning', 'open',
                    '{}'::jsonb, now(), now())
            """
        ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
        {"bid": UUID(block_id)},
    )
    cutoff = _today_utc() + timedelta(days=3)
    await admin_session.execute(
        text(
            """
            INSERT INTO irrigation_schedules (id, block_id, scheduled_for,
                                              recommended_mm, status,
                                              created_at, updated_at)
            VALUES (gen_random_uuid(), :bid, :sf, 5, 'pending', now(), now())
            """
        ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
        {"bid": UUID(block_id), "sf": cutoff},
    )
    await admin_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        preview = await c.get(f"/api/v1/blocks/{block_id}/inactivate-preview")
        assert preview.status_code == 200, preview.text
        pdata = preview.json()
        assert pdata["alerts_resolved"] == 1
        assert pdata["irrigation_skipped"] == 1

        result = await c.post(
            f"/api/v1/blocks/{block_id}/inactivate",
            json={"reason": "merged"},
        )
        assert result.status_code == 200, result.text
        rdata = result.json()
        assert rdata["alerts_resolved"] == 1
        assert rdata["irrigation_skipped"] == 1
        assert rdata["active_to"] == _today_utc().isoformat()

        # GET block (without include_archived) should 404 now.
        get_resp = await c.get(f"/api/v1/blocks/{block_id}")
        assert get_resp.status_code == 404

    # Verify the alert was actually resolved + irrigation skipped.
    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    alert_status = (
        await admin_session.execute(
            text("SELECT status FROM alerts WHERE block_id = :bid").bindparams(
                bindparam("bid", type_=PG_UUID(as_uuid=True))
            ),
            {"bid": UUID(block_id)},
        )
    ).scalar_one()
    assert alert_status == "resolved"
    irrig_status = (
        await admin_session.execute(
            text("SELECT status FROM irrigation_schedules WHERE block_id = :bid").bindparams(
                bindparam("bid", type_=PG_UUID(as_uuid=True))
            ),
            {"bid": UUID(block_id)},
        )
    ).scalar_one()
    assert irrig_status == "skipped"


@pytest.mark.asyncio
async def test_reactivate_block_clears_active_window(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "life-react")
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _square_polygon(31.201, 30.001)},
        )
        block_id = block.json()["id"]

        # Inactivate, then reactivate.
        inact = await c.post(f"/api/v1/blocks/{block_id}/inactivate", json={"reason": "test"})
        assert inact.status_code == 200, inact.text
        react = await c.post(f"/api/v1/blocks/{block_id}/reactivate")
        assert react.status_code == 200, react.text

        # GET should now succeed and show active_to = null again.
        get_resp = await c.get(f"/api/v1/blocks/{block_id}")
        assert get_resp.status_code == 200, get_resp.text
        body = get_resp.json()
        assert body["active_to"] is None
        assert body["is_active"] is True


@pytest.mark.asyncio
async def test_inactivate_farm_cascades_to_blocks(
    admin_session: AsyncSession,
) -> None:
    tenant, context = await _bootstrap(admin_session, "life-farm-cascade")
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        block_ids = []
        for i, lon_off in enumerate((0.001, 0.003, 0.005)):
            b = await c.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={
                    "code": f"B{i + 1}",
                    "boundary": _square_polygon(31.2 + lon_off, 30.001),
                },
            )
            assert b.status_code == 201, b.text
            block_ids.append(b.json()["id"])

        # Preview should show 3 blocks
        preview = await c.get(f"/api/v1/farms/{farm_id}/inactivate-preview")
        assert preview.status_code == 200, preview.text
        assert preview.json()["block_count"] == 3

        # Inactivate the farm
        result = await c.post(f"/api/v1/farms/{farm_id}/inactivate", json={"reason": "wind-down"})
        assert result.status_code == 200, result.text
        assert result.json()["block_count"] == 3

        # Every block GET now 404s
        for bid in block_ids:
            get_resp = await c.get(f"/api/v1/blocks/{bid}")
            assert get_resp.status_code == 404

    # Verify in the database that every block carries active_to + deleted_at.
    await admin_session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
    rows = (
        await admin_session.execute(
            text("SELECT id, active_to, deleted_at FROM blocks WHERE farm_id = :fid").bindparams(
                bindparam("fid", type_=PG_UUID(as_uuid=True))
            ),
            {"fid": UUID(farm_id)},
        )
    ).all()
    assert len(rows) == 3
    for r in rows:
        assert r.active_to is not None
        assert r.deleted_at is not None


@pytest.mark.asyncio
async def test_reactivate_farm_with_restore_blocks(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "life-farm-restore")
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _square_polygon(31.201, 30.001)},
        )
        await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B2", "boundary": _square_polygon(31.203, 30.001)},
        )
        await c.post(f"/api/v1/farms/{farm_id}/inactivate", json={"reason": "x"})

        react = await c.post(f"/api/v1/farms/{farm_id}/reactivate", json={"restore_blocks": True})
        assert react.status_code == 200, react.text
        assert react.json()["restored_block_count"] == 2

        # Farm + blocks reachable again.
        list_resp = await c.get(f"/api/v1/farms/{farm_id}/blocks")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) == 2


@pytest.mark.asyncio
async def test_list_blocks_excludes_inactive_by_default(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "life-list")
    app = build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        keep = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "K", "boundary": _square_polygon(31.201, 30.001)},
        )
        zap = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "Z", "boundary": _square_polygon(31.203, 30.001)},
        )
        await c.post(f"/api/v1/blocks/{zap.json()['id']}/inactivate", json={"reason": "test"})

        default = await c.get(f"/api/v1/farms/{farm_id}/blocks")
        assert default.status_code == 200
        codes = sorted(b["code"] for b in default.json()["items"])
        assert codes == ["K"]

        inclusive = await c.get(f"/api/v1/farms/{farm_id}/blocks?include_inactive=true")
        assert inclusive.status_code == 200
        codes_all = sorted(b["code"] for b in inclusive.json()["items"])
        assert codes_all == ["K", "Z"]

        del keep  # silence unused-variable lint
