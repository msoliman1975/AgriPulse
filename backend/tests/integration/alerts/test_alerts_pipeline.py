"""Integration tests for the alerts pipeline (PR-5).

Exercises the full path: seed an aggregate row with a strongly-negative
``baseline_deviation`` → trigger the engine → assert an alert lands →
acknowledge → resolve. Plus the duplicate-suppression invariant via the
partial UNIQUE on (block_id, rule_code).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.service import get_alerts_service
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from app.shared.db.session import AsyncSessionLocal
from tests.integration.farms.conftest import make_context
from tests.integration.farms.test_farms_crud import _create_user_in_tenant

pytestmark = [pytest.mark.integration]


async def _seed_block_with_ndvi_row(
    admin_session: AsyncSession,
    schema_name: str,
    *,
    deviation: Decimal,
) -> tuple[UUID, UUID]:
    """Seed a tenant farm + block + a single aggregate row with the
    given ``baseline_deviation``. Returns ``(farm_id, block_id)``."""
    farm_id = uuid4()
    block_id = uuid4()
    product_id = uuid4()
    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema_name}", public'))
    await admin_session.execute(
        text(
            "INSERT INTO farms (id, code, name, boundary, boundary_utm, centroid, area_m2, status) "
            "VALUES (:fid, 'PR5-FARM', 'PR-5 Farm', "
            "        'SRID=4326;MULTIPOLYGON(((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1)))'::geometry, "
            "        'SRID=32636;MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        100, 'active')"
        ).bindparams(bindparam("fid", type_=PG_UUID(as_uuid=True))),
        {"fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO blocks (id, farm_id, code, boundary, boundary_utm, centroid, area_m2, "
            "                    aoi_hash, unit_type, status) "
            "VALUES (:bid, :fid, 'B-PR5', "
            "        'SRID=4326;POLYGON((31.2 30.1, 31.21 30.1, 31.21 30.11, 31.2 30.11, 31.2 30.1))'::geometry, "
            "        'SRID=32636;POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'::geometry, "
            "        'SRID=4326;POINT(31.205 30.105)'::geometry, "
            "        50, 'pr5-aoi-hash', 'block', 'active')"
        ).bindparams(
            bindparam("bid", type_=PG_UUID(as_uuid=True)),
            bindparam("fid", type_=PG_UUID(as_uuid=True)),
        ),
        {"bid": block_id, "fid": farm_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO block_index_aggregates ("
            "  time, block_id, index_code, product_id, mean, "
            "  valid_pixel_count, total_pixel_count, stac_item_id, baseline_deviation"
            ") VALUES ("
            "  :time, :block_id, 'ndvi', :product_id, 0.45, "
            "  100, 100, 'pr5/scene', :deviation"
            ")"
        ).bindparams(
            bindparam("block_id", type_=PG_UUID(as_uuid=True)),
            bindparam("product_id", type_=PG_UUID(as_uuid=True)),
        ),
        {
            "time": datetime.now(UTC).replace(microsecond=0),
            "block_id": block_id,
            "product_id": product_id,
            "deviation": deviation,
        },
    )
    await admin_session.commit()
    return farm_id, block_id


@pytest.mark.asyncio
async def test_evaluate_block_opens_alert_for_severe_drop(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr5-engine-fires",
        name="PR-5 Engine Fires",
        contact_email="ops@pr5-fires.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            summary = await svc.evaluate_block(
                block_id=block_id, actor_user_id=None, tenant_schema=tenant.schema_name
            )
    assert summary["alerts_opened"] == 1
    assert summary["rules_evaluated"] >= 1

    rows = (
        await admin_session.execute(
            text(
                f'SELECT rule_code, severity, status FROM "{tenant.schema_name}".alerts '
                "WHERE block_id = :bid"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].rule_code == "ndvi_severe_drop"
    assert rows[0].severity == "critical"
    assert rows[0].status == "open"


@pytest.mark.asyncio
async def test_re_evaluating_does_not_create_duplicate_alert(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr5-idempotent",
        name="PR-5 Idempotent",
        contact_email="ops@pr5-idemp.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    for _ in range(2):
        async with factory() as session, session.begin():
            await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
            async with factory() as public_session:
                svc = get_alerts_service(tenant_session=session, public_session=public_session)
                await svc.evaluate_block(
                    block_id=block_id,
                    actor_user_id=None,
                    tenant_schema=tenant.schema_name,
                )

    count = (
        await admin_session.execute(
            text(
                f'SELECT count(*) FROM "{tenant.schema_name}".alerts '
                "WHERE block_id = :bid AND rule_code = 'ndvi_severe_drop'"
            ).bindparams(bindparam("bid", type_=PG_UUID(as_uuid=True))),
            {"bid": block_id},
        )
    ).scalar_one()
    assert count == 1, "duplicate-active-alert suppression failed"


@pytest.mark.asyncio
async def test_override_with_is_disabled_silences_rule(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr5-disabled",
        name="PR-5 Disabled",
        contact_email="ops@pr5-disabled.test",
    )
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.upsert_override(
                rule_code="ndvi_severe_drop",
                modified_conditions=None,
                modified_actions=None,
                modified_severity=None,
                is_disabled=True,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )
            summary = await svc.evaluate_block(
                block_id=block_id, actor_user_id=None, tenant_schema=tenant.schema_name
            )
    # The disabled rule contributes to skipped count, no alert opens.
    assert summary["alerts_opened"] == 0
    assert summary["rules_skipped_disabled"] >= 1


@pytest.mark.asyncio
async def test_acknowledge_then_resolve_via_http(
    admin_session: AsyncSession,
) -> None:
    """Full HTTP roundtrip — list, acknowledge, resolve."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr5-http",
        name="PR-5 HTTP",
        contact_email="ops@pr5-http.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    # Fire the engine first so an alert exists.
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.evaluate_block(
                block_id=block_id, actor_user_id=user_id, tenant_schema=tenant.schema_name
            )

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    # build_app from the farms conftest only mounts farms — we need
    # alerts too. Easiest: build it inline.
    from fastapi import FastAPI

    from app.core.errors import install_exception_handlers
    from app.modules.alerts.router import router as alerts_router
    from app.modules.farms.router import router as farms_router
    from tests.integration.farms.conftest import StubAuth

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(alerts_router)
    app.add_middleware(StubAuth, context=context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/alerts", params={"block_id": str(block_id)})
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert len(rows) == 1
        alert_id = rows[0]["id"]
        assert rows[0]["status"] == "open"

        # Acknowledge.
        ack = await client.patch(f"/api/v1/alerts/{alert_id}", json={"acknowledge": True})
        assert ack.status_code == 200, ack.text
        assert ack.json()["status"] == "acknowledged"
        assert ack.json()["acknowledged_at"] is not None

        # Resolve.
        resolved = await client.patch(f"/api/v1/alerts/{alert_id}", json={"resolve": True})
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "resolved"

        # Snooze with a future timestamp on a brand-new evaluation.
        # First we must have a fresh alert; resolve doesn't re-fire so
        # there's no new alert. We just verify the validation path.
        bad = await client.patch(
            f"/api/v1/alerts/{alert_id}",
            json={"acknowledge": True, "resolve": True},
        )
        assert bad.status_code == 400, bad.text


@pytest.mark.asyncio
async def test_alerts_list_filters_by_status(
    admin_session: AsyncSession,
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr5-filter",
        name="PR-5 Filter",
        contact_email="ops@pr5-filter.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.evaluate_block(
                block_id=block_id, actor_user_id=None, tenant_schema=tenant.schema_name
            )

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    from fastapi import FastAPI

    from app.core.errors import install_exception_handlers
    from app.modules.alerts.router import router as alerts_router
    from tests.integration.farms.conftest import StubAuth

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(alerts_router)
    app.add_middleware(StubAuth, context=context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        only_open = await client.get("/api/v1/alerts", params={"status": "open"})
        assert only_open.status_code == 200
        assert all(r["status"] == "open" for r in only_open.json())

        only_resolved = await client.get("/api/v1/alerts", params={"status": "resolved"})
        assert only_resolved.status_code == 200
        assert only_resolved.json() == []


# ---------------------------------------------------------------------------
# prescription_activity_id (PR-1b — added 2026-05-07)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_response_carries_prescription_activity_id(
    admin_session: AsyncSession,
) -> None:
    """The new column round-trips through the engine and HTTP — for now
    the engine writes NULL but the FE deep-link contract is locked."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr1b-prescription",
        name="PR-1b Prescription",
        contact_email="ops@pr1b.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    _farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.evaluate_block(
                block_id=block_id, actor_user_id=None, tenant_schema=tenant.schema_name
            )

    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    from fastapi import FastAPI

    from app.core.errors import install_exception_handlers
    from app.modules.alerts.router import router as alerts_router
    from tests.integration.farms.conftest import StubAuth

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(alerts_router)
    app.add_middleware(StubAuth, context=context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/v1/alerts", params={"block_id": str(block_id)})
        assert listed.status_code == 200, listed.text
        rows = listed.json()
        assert len(rows) == 1
        # Engine writes NULL for now; the field must still be present in
        # the response so the FE deep-link contract is stable.
        assert "prescription_activity_id" in rows[0]
        assert rows[0]["prescription_activity_id"] is None


# Suppress unused-import lint for `timedelta` referenced via test seeds.
_ = timedelta
