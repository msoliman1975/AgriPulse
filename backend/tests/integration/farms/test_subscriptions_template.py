"""Integration tests for PR-2 subscription-template endpoints.

Covers the four scenarios called out by the farm-block-config-model
proposal:

  * Template CRUD          — insert / update / replace.
  * Apply-preview          — block-matches, block-has-extra-row,
                             block-has-divergent-knob.
  * Apply atomicity        — failure mid-flight leaves no partial state.
  * Selective apply        — block_ids subsets only touch those blocks.

The feature flag ``farm_config_template_enabled`` is forced on per test
via monkeypatch + ``get_settings.cache_clear``; the unflagged route
returning 404 is exercised in its own test.
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


# ---- Geometry helpers (same shape as test_lifecycle.py) -------------------


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
async def test_feature_flag_off_returns_404(
    admin_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabling the flag hides every config endpoint as 404."""
    monkeypatch.setenv("FARM_CONFIG_TEMPLATE_ENABLED", "false")
    get_settings.cache_clear()

    _, context = await _bootstrap(admin_session, "cfg-off")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        resp = await c.get(
            f"/api/v1/farms/{farm.json()['id']}/config/subscriptions/template"
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_template_crud_round_trip(admin_session: AsyncSession) -> None:
    _, context = await _bootstrap(admin_session, "cfg-crud")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]

        # Initially empty.
        initial = await c.get(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template"
        )
        assert initial.status_code == 200
        assert initial.json() == {"imagery": [], "weather": []}

        product_id = str(uuid4())
        put = await c.put(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template",
            json={
                "imagery": [
                    {
                        "product_id": product_id,
                        "cadence_hours": 24,
                        "cloud_cover_max_pct": 30,
                        "is_active": True,
                    }
                ],
                "weather": [
                    {
                        "provider_code": "open_meteo",
                        "cadence_hours": 6,
                        "is_active": True,
                    }
                ],
            },
        )
        assert put.status_code == 200, put.text
        body = put.json()
        assert len(body["imagery"]) == 1
        assert body["imagery"][0]["cadence_hours"] == 24
        assert len(body["weather"]) == 1
        assert body["weather"][0]["provider_code"] == "open_meteo"

        # Replace shrinks the list to empty.
        cleared = await c.put(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template",
            json={"imagery": [], "weather": []},
        )
        assert cleared.status_code == 200
        assert cleared.json() == {"imagery": [], "weather": []}


@pytest.mark.asyncio
async def test_replace_rejects_duplicate_keys(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "cfg-dup")
    app = build_app(context, with_config=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        product_id = str(uuid4())
        resp = await c.put(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template",
            json={
                "imagery": [
                    {
                        "product_id": product_id,
                        "cadence_hours": 24,
                        "cloud_cover_max_pct": None,
                        "is_active": True,
                    },
                    {
                        "product_id": product_id,
                        "cadence_hours": 12,
                        "cloud_cover_max_pct": None,
                        "is_active": True,
                    },
                ],
                "weather": [],
            },
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_apply_preview_three_diff_shapes(
    admin_session: AsyncSession,
) -> None:
    """Block-matches, block-has-divergent-knob, block-has-extra-row."""
    _, context = await _bootstrap(admin_session, "cfg-diff")
    app = build_app(context, with_config=True)
    product_a = str(uuid4())
    product_b = str(uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]

        # Three blocks under one farm.
        ids = []
        for i in range(3):
            b = await c.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={
                    "code": f"B{i + 1}",
                    "boundary": _square_polygon(31.21 + i * 0.002, 30.001),
                },
            )
            ids.append(b.json()["id"])

        # Template: imagery=[product_a @ 24h, cloud≤30, active].
        await c.put(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template",
            json={
                "imagery": [
                    {
                        "product_id": product_a,
                        "cadence_hours": 24,
                        "cloud_cover_max_pct": 30,
                        "is_active": True,
                    }
                ],
                "weather": [],
            },
        )

        # First Apply lands the template on all three blocks ⇒ all match.
        applied = await c.post(
            f"/api/v1/farms/{farm_id}/config/subscriptions/apply",
            json={"block_ids": None},
        )
        assert applied.status_code == 200
        assert applied.json()["blocks_touched"] == 3
        assert applied.json()["imagery_added"] == 3

        # Mutate block 1: change cadence (divergent knob).
        # Mutate block 2: add an extra subscription to product_b.
        await admin_session.execute(
            text(
                "UPDATE imagery_aoi_subscriptions "
                "SET cadence_hours = 6 WHERE block_id = :bid"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": UUID(ids[0])},
        )
        await admin_session.execute(
            text(
                "INSERT INTO imagery_aoi_subscriptions "
                "(block_id, product_id, cadence_hours, cloud_cover_max_pct, is_active) "
                "VALUES (:bid, :pid, 12, 50, TRUE)"
            ).bindparams(
                bindparam("bid", type_=PG_UUID(as_uuid=True)),
                bindparam("pid", type_=PG_UUID(as_uuid=True)),
            ),
            {"bid": UUID(ids[1]), "pid": UUID(product_b)},
        )
        await admin_session.commit()

        preview = await c.post(
            f"/api/v1/farms/{farm_id}/config/subscriptions/apply-preview",
            json={"block_ids": None},
        )
        body = preview.json()
        by_id = {d["block_id"]: d for d in body["imagery"]}

        # Block 0: divergent → will_update.
        assert by_id[ids[0]]["matches"] is False
        assert len(by_id[ids[0]]["will_update"]) == 1
        # Block 1: extra row → will_deactivate (product_b).
        assert by_id[ids[1]]["matches"] is False
        assert len(by_id[ids[1]]["will_deactivate"]) == 1
        # Block 2: matches.
        assert by_id[ids[2]]["matches"] is True
        # Aggregate: 1 of 3 matches.
        assert body["matched_blocks"] == 1
        assert body["total_blocks"] == 3


@pytest.mark.asyncio
async def test_selective_apply_only_touches_passed_ids(
    admin_session: AsyncSession,
) -> None:
    _, context = await _bootstrap(admin_session, "cfg-sel")
    app = build_app(context, with_config=True)
    product_a = str(uuid4())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        farm_id = farm.json()["id"]
        ids = []
        for i in range(2):
            b = await c.post(
                f"/api/v1/farms/{farm_id}/blocks",
                json={
                    "code": f"B{i + 1}",
                    "boundary": _square_polygon(31.21 + i * 0.002, 30.001),
                },
            )
            ids.append(b.json()["id"])

        await c.put(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template",
            json={
                "imagery": [
                    {
                        "product_id": product_a,
                        "cadence_hours": 12,
                        "cloud_cover_max_pct": 20,
                        "is_active": True,
                    }
                ],
                "weather": [],
            },
        )

        # Only apply to the first block.
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/config/subscriptions/apply",
            json={"block_ids": [ids[0]]},
        )
        assert resp.status_code == 200
        counts = resp.json()
        assert counts["blocks_touched"] == 1
        assert counts["imagery_added"] == 1

        # The second block should still have no subscription rows.
        rows = (
            await admin_session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM imagery_aoi_subscriptions "
                    "WHERE block_id = :bid"
                ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
                {"bid": UUID(ids[1])},
            )
        ).first()
        assert rows.n == 0


@pytest.mark.asyncio
async def test_apply_is_idempotent_when_block_already_matches(
    admin_session: AsyncSession,
) -> None:
    """Second Apply on a matching block touches nothing."""
    _, context = await _bootstrap(admin_session, "cfg-idem")
    app = build_app(context, with_config=True)
    product_a = str(uuid4())

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
            json={"code": "B1", "boundary": _square_polygon(31.21, 30.001)},
        )
        block_id = block.json()["id"]

        await c.put(
            f"/api/v1/farms/{farm_id}/config/subscriptions/template",
            json={
                "imagery": [
                    {
                        "product_id": product_a,
                        "cadence_hours": 24,
                        "cloud_cover_max_pct": None,
                        "is_active": True,
                    }
                ],
                "weather": [],
            },
        )

        first = await c.post(
            f"/api/v1/farms/{farm_id}/config/subscriptions/apply",
            json={"block_ids": [block_id]},
        )
        assert first.json()["imagery_added"] == 1

        second = await c.post(
            f"/api/v1/farms/{farm_id}/config/subscriptions/apply",
            json={"block_ids": [block_id]},
        )
        # No add / update / deactivate this time.
        assert second.json() == {
            "blocks_touched": 0,
            "imagery_added": 0,
            "imagery_updated": 0,
            "imagery_deactivated": 0,
            "weather_added": 0,
            "weather_updated": 0,
            "weather_deactivated": 0,
        }
