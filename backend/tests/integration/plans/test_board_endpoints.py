"""Integration tests for board PR-3 endpoints.

Covers:
  * POST /farms/{farm_id}/activities — flat (no-plan) create
  * POST /farms/{farm_id}/activities/bulk — multi-cell bulk create
    incl. skip_existing dedup
  * GET  /farms/{farm_id}/board — grid response with blocks +
    activities + attached resource chips
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.plans.router import router as plans_router
from app.modules.resources.router import router as resources_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_blocks_unit_type import _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(plans_router)
    app.include_router(resources_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _bootstrap_two_blocks(
    admin_session: AsyncSession, slug: str
) -> tuple[object, str, str, str]:
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
        farm = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "BD3-FARM",
                    "name": "Board PR-3 farm",
                    "boundary": _square(31.70, 30.70),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()
        b1 = (
            await client.post(
                f"/api/v1/farms/{farm['id']}/blocks",
                json={"code": "B1", "boundary": _polygon(31.71, 30.71)},
            )
        ).json()
        b2 = (
            await client.post(
                f"/api/v1/farms/{farm['id']}/blocks",
                json={"code": "B2", "boundary": _polygon(31.72, 30.72)},
            )
        ).json()
    return context, farm["id"], b1["id"], b2["id"]


@pytest.mark.asyncio
async def test_flat_activity_create_no_plan(admin_session: AsyncSession) -> None:
    context, farm_id, b1_id, _b2 = await _bootstrap_two_blocks(admin_session, "bd3-flat")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sd = (date.today() + timedelta(days=3)).isoformat()
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/activities",
            json={
                "block_id": b1_id,
                "activity_type": "irrigation",
                "scheduled_date": sd,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["plan_id"] is None
        assert body["farm_id"] == farm_id
        assert body["block_id"] == b1_id
        assert body["status"] == "scheduled"


@pytest.mark.asyncio
async def test_bulk_create_skips_duplicates(admin_session: AsyncSession) -> None:
    context, farm_id, b1, b2 = await _bootstrap_two_blocks(admin_session, "bd3-bulk")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sd = (date.today() + timedelta(days=4)).isoformat()
        # First seed one activity on B1 with the same triple
        await client.post(
            f"/api/v1/farms/{farm_id}/activities",
            json={"block_id": b1, "activity_type": "spraying", "scheduled_date": sd},
        )
        # Bulk-add to both B1 and B2; B1's row should be skipped.
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/activities/bulk",
            json={
                "cells": [
                    {"block_id": b1, "scheduled_date": sd},
                    {"block_id": b2, "scheduled_date": sd},
                ],
                "activity_type": "spraying",
                "skip_existing": True,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert len(body["created"]) == 1
        assert body["created"][0]["block_id"] == b2
        assert len(body["skipped"]) == 1
        assert body["skipped"][0]["block_id"] == b1


@pytest.mark.asyncio
async def test_bulk_skip_false_creates_duplicates(
    admin_session: AsyncSession,
) -> None:
    context, farm_id, b1, _ = await _bootstrap_two_blocks(admin_session, "bd3-bulk-nodedupe")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sd = (date.today() + timedelta(days=2)).isoformat()
        await client.post(
            f"/api/v1/farms/{farm_id}/activities",
            json={"block_id": b1, "activity_type": "fertilizing", "scheduled_date": sd},
        )
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/activities/bulk",
            json={
                "cells": [{"block_id": b1, "scheduled_date": sd}],
                "activity_type": "fertilizing",
                "skip_existing": False,
            },
        )
        body = resp.json()
        assert len(body["created"]) == 1
        assert body["skipped"] == []


@pytest.mark.asyncio
async def test_board_includes_blocks_and_activities_with_resources(
    admin_session: AsyncSession,
) -> None:
    context, farm_id, b1, b2 = await _bootstrap_two_blocks(admin_session, "bd3-board")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sd = date.today() + timedelta(days=1)
        # Activity on B1, with one worker attached
        activity = (
            await client.post(
                f"/api/v1/farms/{farm_id}/activities",
                json={
                    "block_id": b1,
                    "activity_type": "irrigation",
                    "scheduled_date": sd.isoformat(),
                },
            )
        ).json()
        worker = (
            await client.post(
                f"/api/v1/farms/{farm_id}/resources",
                json={"kind": "worker", "name": "Ahmed", "role": "operator"},
            )
        ).json()
        attach = await client.post(f"/api/v1/activities/{activity['id']}/resources/{worker['id']}")
        assert attach.status_code == 201

        # Activity outside the window — should be excluded
        await client.post(
            f"/api/v1/farms/{farm_id}/activities",
            json={
                "block_id": b2,
                "activity_type": "spraying",
                "scheduled_date": (sd + timedelta(days=60)).isoformat(),
            },
        )

        resp = await client.get(
            f"/api/v1/farms/{farm_id}/board",
            params={"week_start": sd.isoformat(), "weeks": 4},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["farm_id"] == farm_id
        assert body["weeks"] == 4
        assert {b["id"] for b in body["blocks"]} == {b1, b2}
        assert len(body["activities"]) == 1
        a = body["activities"][0]
        assert a["block_id"] == b1
        assert len(a["resources"]) == 1
        assert a["resources"][0]["name"] == "Ahmed"
        assert a["resources"][0]["role"] == "operator"
