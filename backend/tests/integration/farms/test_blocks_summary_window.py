"""`/farms/{id}/blocks/summary` — recent-window lookup + stale fallback.

The latest-index lookup runs in two passes: a time-bounded one (so
TimescaleDB can exclude chunks — that bound is the whole performance fix,
see `_RECENT_WINDOW_DAYS`) and an unbounded sweep for any block the window
turned up nothing for.

These tests pin the part that could silently regress: a block whose only
readings predate the window must still report them. If someone later drops
the fallback to "simplify", a block that stopped being imaged would quietly
render as `unknown` on the map instead of showing its last known value.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.blocks_summary_router import _RECENT_WINDOW_DAYS
from app.modules.farms.blocks_summary_router import router as summary_router
from app.modules.farms.router import router as farms_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import StubAuth, make_context

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


def _polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
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


def _build_app(context) -> FastAPI:
    """farms router (to create the fixtures) + the summary router under test."""
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(summary_router)
    app.add_middleware(StubAuth, context=context)
    return app


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
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, context


async def _insert_index(
    session: AsyncSession,
    *,
    schema: str,
    block_id: UUID,
    at: datetime,
    mean: float,
    index_code: str = "ndvi",
) -> None:
    await session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await session.execute(
        text(
            "INSERT INTO block_index_aggregates "
            "(time, block_id, index_code, product_id, mean, "
            " valid_pixel_count, total_pixel_count, stac_item_id) "
            "VALUES (:t, :b, :code, :p, :mean, 100, 100, :scene)"
        ).bindparams(
            bindparam("b", type_=PG_UUID(as_uuid=True)),
            bindparam("p", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "t": at,
            "b": block_id,
            "code": index_code,
            "p": uuid4(),
            "mean": mean,
            "scene": f"scene-{at.isoformat()}",
        },
    )
    await session.commit()


async def _make_farm_with_block(client: AsyncClient) -> tuple[str, str]:
    farm = await client.post(
        "/api/v1/farms",
        json={"code": "F1", "name": "F1", "boundary": _square(31.2, 30.0)},
    )
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]
    block = await client.post(
        f"/api/v1/farms/{farm_id}/blocks",
        json={"code": "B1", "name": "B1", "boundary": _polygon(31.201, 30.001)},
    )
    assert block.status_code == 201, block.text
    return farm_id, block.json()["id"]


@pytest.mark.asyncio
async def test_recent_reading_is_reported(admin_session: AsyncSession) -> None:
    """The common case: a reading inside the window comes back from pass one."""
    tenant, context = await _bootstrap(admin_session, "bsw-recent")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=datetime.now(UTC) - timedelta(days=2),
            mean=0.71,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] == pytest.approx(0.71)
    assert unit["health"] == "healthy"


@pytest.mark.asyncio
async def test_reading_older_than_the_window_still_reported(
    admin_session: AsyncSession,
) -> None:
    """A block whose only reading predates the window falls back, not to `unknown`.

    This is the regression guard: the bounded first pass finds nothing for
    this block, so the unbounded sweep has to pick it up.
    """
    tenant, context = await _bootstrap(admin_session, "bsw-stale")
    app = _build_app(context)

    stale_at = datetime.now(UTC) - timedelta(days=_RECENT_WINDOW_DAYS + 45)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=stale_at,
            mean=0.31,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] == pytest.approx(0.31), "stale reading was dropped"
    # 0.31 < 0.4, so the health classifier calls it critical — proves the
    # value actually reached classification rather than defaulting.
    assert unit["health"] == "critical"
    assert unit["last_index_at"] is not None


@pytest.mark.asyncio
async def test_recent_reading_wins_over_older_one(admin_session: AsyncSession) -> None:
    """With both, the in-window value is reported — the sweep must not override it."""
    tenant, context = await _bootstrap(admin_session, "bsw-both")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=datetime.now(UTC) - timedelta(days=_RECENT_WINDOW_DAYS + 30),
            mean=0.20,
        )
        await _insert_index(
            admin_session,
            schema=tenant.schema_name,
            block_id=UUID(block_id),
            at=datetime.now(UTC) - timedelta(days=3),
            mean=0.66,
        )

        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] == pytest.approx(0.66)


@pytest.mark.asyncio
async def test_block_with_no_readings_is_unknown(admin_session: AsyncSession) -> None:
    """Neither pass finds anything — the block still appears, as `unknown`."""
    _, context = await _bootstrap(admin_session, "bsw-none")
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, block_id = await _make_farm_with_block(c)
        resp = await c.get(f"/api/v1/farms/{farm_id}/blocks/summary")

    assert resp.status_code == 200, resp.text
    unit = next(u for u in resp.json()["units"] if u["id"] == block_id)
    assert unit["ndvi_current"] is None
    assert unit["health"] == "unknown"
    assert unit["last_index_at"] is None
