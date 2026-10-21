"""The pipeline queue names its blocks.

`GET /integrations/health/queue` returned `block_id` and nothing else, so
the Queue tab could only print a raw uuid — the sole per-row identifier on
that list, matching nothing an operator can see on the map.

Every one of the four branches (weather/imagery x overdue/running) now
carries `block_code` + `block_name`. Three of them already joined `blocks`;
the weather-running branch read straight off `weather_ingestion_attempts`
and had no join at all, so it gets a LEFT join — left, because a stuck
attempt on a deleted block is exactly the row an operator must still see.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.integrations_health.router import router as health_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import RequestContext, TenantRole
from tests.integration.farms.conftest import StubAuth, make_context

pytestmark = [pytest.mark.integration]


def _square(lon: float, lat: float, side: float = 0.005) -> dict[str, object]:
    ring = [
        [lon, lat],
        [lon + side, lat],
        [lon + side, lat + side],
        [lon, lat + side],
        [lon, lat],
    ]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def _square_polygon(lon: float, lat: float, side: float = 0.001) -> dict[str, object]:
    ring = [
        [lon, lat],
        [lon + side, lat],
        [lon + side, lat + side],
        [lon, lat + side],
        [lon, lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _build_app(context: RequestContext) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(health_router)
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
    await session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": uuid4(), "uid": user_id, "tid": tenant_id},
    )


@pytest.mark.asyncio
async def test_queue_rows_carry_block_code_and_name(admin_session: AsyncSession) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="ih-queue-labels",
        name="ih-queue-labels",
        contact_email="ops@ih-queue-labels.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = _build_app(context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={"code": "F", "name": "F", "boundary": _square(31.2, 30.0)},
        )
        assert farm.status_code == 201, farm.text
        farm_id = UUID(farm.json()["id"])

        named = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "B-01",
                "name": "North Mango",
                "boundary": _square_polygon(31.201, 30.001),
            },
        )
        assert named.status_code == 201, named.text
        named_id = UUID(named.json()["id"])

        # Bulk AOI upload creates blocks with a code and no name, so the
        # response model must tolerate a null name on this path too.
        unnamed = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B-02", "boundary": _square_polygon(31.203, 30.001)},
        )
        assert unnamed.status_code == 201, unnamed.text
        assert unnamed.json()["name"] is None
        unnamed_id = UUID(unnamed.json()["id"])

        # --- Seed one row into each of the four queue branches ----------
        await admin_session.execute(
            text(f'SET LOCAL search_path TO "{tenant.schema_name}", public')
        )

        weather_sub = uuid4()
        await admin_session.execute(
            text(
                "INSERT INTO weather_subscriptions (id, block_id, provider_code, "
                " cadence_hours, is_active, last_successful_ingest_at) "
                "VALUES (:id, :b, 'open_meteo', 3, true, now() - interval '10 hours')"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": weather_sub, "b": named_id},
        )
        # A running weather attempt on the UNNAMED block — this is the branch
        # that had no join to `blocks` at all.
        await admin_session.execute(
            text(
                "INSERT INTO weather_ingestion_attempts (id, subscription_id, block_id, "
                " farm_id, provider_code, status, started_at) "
                "VALUES (:id, :s, :b, :f, 'open_meteo', 'running', now())"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("s", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("f", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": uuid4(), "s": weather_sub, "b": unnamed_id, "f": farm_id},
        )

        product_id = (
            await admin_session.execute(text("SELECT id FROM public.imagery_products LIMIT 1"))
        ).scalar_one()
        imagery_sub = uuid4()
        await admin_session.execute(
            text(
                "INSERT INTO imagery_aoi_subscriptions (id, block_id, product_id, "
                " cadence_hours, is_active, last_successful_ingest_at) "
                "VALUES (:id, :b, :p, 24, true, now() - interval '48 hours')"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": imagery_sub, "b": named_id, "p": product_id},
        )
        await admin_session.execute(
            text(
                "INSERT INTO imagery_ingestion_jobs (id, subscription_id, block_id, "
                " product_id, scene_id, scene_datetime, status, requested_at) "
                "VALUES (:id, :s, :b, :p, 'S2A_TEST_SCENE', now(), 'running', now())"
            ).bindparams(
                bindparam("id", type_=PG_UUID(as_uuid=True)),
                bindparam("s", type_=PG_UUID(as_uuid=True)),
                bindparam("b", type_=PG_UUID(as_uuid=True)),
                bindparam("p", type_=PG_UUID(as_uuid=True)),
            ),
            {"id": uuid4(), "s": imagery_sub, "b": named_id, "p": product_id},
        )
        await admin_session.commit()

        resp = await c.get("/api/v1/integrations/health/queue")
        assert resp.status_code == 200, resp.text
        rows = resp.json()

        # All four branches produced a row, and none of them is unlabelled.
        seen = {(r["kind"], r["state"]) for r in rows}
        assert ("weather", "overdue") in seen
        assert ("weather", "running") in seen
        assert ("imagery", "overdue") in seen
        assert ("imagery", "running") in seen
        assert all(r["block_code"] is not None for r in rows), rows

        by_block = {r["block_id"]: r for r in rows}
        assert by_block[str(named_id)]["block_code"] == "B-01"
        assert by_block[str(named_id)]["block_name"] == "North Mango"
        # The weather-running row, off the newly joined branch.
        assert by_block[str(unnamed_id)]["block_code"] == "B-02"
        assert by_block[str(unnamed_id)]["block_name"] is None
