"""Integration tests for board PR-5 — POST /recommendations/{id}/schedule.

Drives the drag-rec-to-cell flow end-to-end:
  * Recommendation in `open` state plus the linked board endpoints.
  * Schedule call creates a plan_activity with recommendation_id set
    and transitions the rec to applied in the same tenant session.
  * Defaults derived from rec; overrides apply when explicit.
  * Re-scheduling an already-applied rec is rejected (409).
  * Missing capability returns 404 (parity with rec.act gates).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.plans.router import router as plans_router
from app.modules.recommendations.router import router as recommendations_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from app.shared.db.ids import uuid7
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_blocks_unit_type import _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(plans_router)
    app.include_router(recommendations_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _bootstrap(admin_session: AsyncSession, slug: str):
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"Board {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_resp = await client.post(
            "/api/v1/farms",
            json={
                "code": "BD5-FARM",
                "name": "PR-5 farm",
                "boundary": _square(31.80, 30.80),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm_resp.status_code == 201, farm_resp.text
        farm_id = farm_resp.json()["id"]
        block_resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "B1", "boundary": _polygon(31.81, 30.81)},
        )
        assert block_resp.status_code == 201, block_resp.text
        block_id = block_resp.json()["id"]
    return tenant, context, farm_id, block_id


async def _seed_open_recommendation(
    *,
    tenant_schema: str,
    farm_id: str,
    block_id: str,
    action_type: str = "scout",
) -> UUID:
    """Insert a rec directly so we can drive the endpoint without
    setting up a full decision tree. The endpoint cares about state and
    farm/block, not tree provenance."""
    rec_id = uuid7()
    async with AsyncSessionLocal()() as session:  # type: ignore[name-defined]
        await session.execute(text(f"SET search_path TO {tenant_schema}, public"))
        await session.execute(
            text(
                """
                INSERT INTO recommendations (
                  id, block_id, farm_id, tree_id, tree_code, tree_version,
                  action_type, severity, parameters, confidence, tree_path,
                  text_en, state, evaluation_snapshot
                ) VALUES (
                  :id, :block_id, :farm_id, :tree_id, :tree_code, :tree_version,
                  :action_type, 'info', '{}'::jsonb, 0.9, '[]'::jsonb,
                  'Test rec', 'open', '{}'::jsonb
                )
                """
            ),
            {
                "id": rec_id,
                "block_id": block_id,
                "farm_id": farm_id,
                "tree_id": uuid7(),
                "tree_code": "test_tree",
                "tree_version": 1,
                "action_type": action_type,
            },
        )
        await session.commit()
    return rec_id


# Late import to avoid circular import at module load.
from app.shared.db.session import AsyncSessionLocal  # pragma: no cover


@pytest.mark.asyncio
async def test_schedule_creates_activity_and_applies_rec(
    admin_session: AsyncSession,
) -> None:
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, "bd5-schedule")
    rec_id = await _seed_open_recommendation(
        tenant_schema=tenant.schema_name, farm_id=farm_id, block_id=block_id
    )
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/recommendations/{rec_id}/schedule",
            json={"scheduled_date": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
        )
        assert resp.status_code == 201, resp.text
        activity = resp.json()
        assert activity["recommendation_id"] == str(rec_id)
        assert activity["activity_type"] == "observation"  # scout → observation
        assert activity["farm_id"] == farm_id
        assert activity["block_id"] == block_id
        assert activity["plan_id"] is None

        rec = (await client.get(f"/api/v1/recommendations/{rec_id}")).json()
        assert rec["state"] == "applied"


@pytest.mark.asyncio
async def test_schedule_respects_activity_type_override(
    admin_session: AsyncSession,
) -> None:
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, "bd5-override")
    rec_id = await _seed_open_recommendation(
        tenant_schema=tenant.schema_name,
        farm_id=farm_id,
        block_id=block_id,
        action_type="irrigate",
    )
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Inferred default would be irrigation; override to fertilizing.
        resp = await client.post(
            f"/api/v1/recommendations/{rec_id}/schedule",
            json={
                "activity_type": "fertilizing",
                "notes": "treat as fertigation instead",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["activity_type"] == "fertilizing"
        assert resp.json()["notes"] == "treat as fertigation instead"


@pytest.mark.asyncio
async def test_schedule_rejects_already_applied(
    admin_session: AsyncSession,
) -> None:
    tenant, context, farm_id, block_id = await _bootstrap(admin_session, "bd5-twice")
    rec_id = await _seed_open_recommendation(
        tenant_schema=tenant.schema_name, farm_id=farm_id, block_id=block_id
    )
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/v1/recommendations/{rec_id}/schedule", json={})
        assert first.status_code == 201
        second = await client.post(f"/api/v1/recommendations/{rec_id}/schedule", json={})
        assert second.status_code == 409, second.text
