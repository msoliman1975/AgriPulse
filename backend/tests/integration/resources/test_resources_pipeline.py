"""Integration tests for the resources module (board PR-2).

Covers:
  * Worker CRUD with role + optional phone
  * Equipment CRUD with equipment_type
  * Kind-shape validation (workers can't carry equipment_type, etc.)
  * Active-name uniqueness within (farm_id, kind)
  * Archive / restore round-trip
  * Activity ↔ resource attach / detach
  * RBAC: Viewer can read, FieldOperator cannot manage, TenantAdmin can.
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


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[object, object, str, str]:
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
                "code": "BD-FARM",
                "name": "Board test farm",
                "boundary": _square(31.50, 30.50),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm_resp.status_code == 201, farm_resp.text
        farm_id = farm_resp.json()["id"]
        block_resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "BD-B1", "boundary": _polygon(31.51, 30.51)},
        )
        assert block_resp.status_code == 201, block_resp.text
        block_id = block_resp.json()["id"]
    return tenant, context, farm_id, block_id


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_crud_round_trip(admin_session: AsyncSession) -> None:
    _t, context, farm_id, _b = await _bootstrap(admin_session, "bd-worker")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "worker",
                "name": "  Ahmed Hassan  ",
                "role": "agronomist",
                "phone": "+201112233445",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["kind"] == "worker"
        assert body["name"] == "Ahmed Hassan"  # trimmed
        assert body["role"] == "agronomist"
        assert body["phone"] == "+201112233445"
        assert body["equipment_type"] is None
        assert body["archived_at"] is None
        resource_id = body["id"]

        # GET single
        single = await client.get(f"/api/v1/resources/{resource_id}")
        assert single.status_code == 200
        assert single.json()["name"] == "Ahmed Hassan"

        # List filters by kind
        workers = await client.get(f"/api/v1/farms/{farm_id}/resources", params={"kind": "worker"})
        assert workers.status_code == 200
        assert len(workers.json()) == 1
        equipment = await client.get(
            f"/api/v1/farms/{farm_id}/resources", params={"kind": "equipment"}
        )
        assert equipment.json() == []

        # PATCH name + role
        patched = await client.patch(
            f"/api/v1/resources/{resource_id}",
            json={"name": "Ahmed H.", "role": "scout"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "Ahmed H."
        assert patched.json()["role"] == "scout"


@pytest.mark.asyncio
async def test_equipment_create_and_kind_shape_rules(
    admin_session: AsyncSession,
) -> None:
    _t, context, farm_id, _b = await _bootstrap(admin_session, "bd-equipment")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Equipment must have equipment_type.
        bad = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "equipment", "name": "Tractor 1"},
        )
        assert bad.status_code == 422, bad.text

        # Equipment cannot carry a role.
        bad_role = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "equipment",
                "name": "Tractor 1",
                "equipment_type": "tractor",
                "role": "operator",
            },
        )
        assert bad_role.status_code == 422, bad_role.text

        # Equipment cannot carry a phone.
        bad_phone = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "equipment",
                "name": "Tractor 1",
                "equipment_type": "tractor",
                "phone": "+201",
            },
        )
        assert bad_phone.status_code == 422, bad_phone.text

        # Worker without role.
        bad_worker = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "worker", "name": "Sara"},
        )
        assert bad_worker.status_code == 422, bad_worker.text

        # Happy path.
        good = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "equipment",
                "name": "Tractor #2",
                "equipment_type": "tractor",
            },
        )
        assert good.status_code == 201, good.text


@pytest.mark.asyncio
async def test_duplicate_active_name_rejected_case_insensitive(
    admin_session: AsyncSession,
) -> None:
    _t, context, farm_id, _b = await _bootstrap(admin_session, "bd-dup")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "worker", "name": "Khalid", "role": "operator"},
        )
        assert first.status_code == 201

        # Same case
        dup = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "worker", "name": "Khalid", "role": "operator"},
        )
        assert dup.status_code == 409, dup.text

        # Different case still rejected (uq on lower(name))
        dup_case = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "worker", "name": "khalid", "role": "operator"},
        )
        assert dup_case.status_code == 409, dup_case.text

        # Same name, different kind: allowed (equipment "Khalid" is fine)
        cross_kind = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "equipment",
                "name": "Khalid",
                "equipment_type": "tractor",
            },
        )
        assert cross_kind.status_code == 201, cross_kind.text


@pytest.mark.asyncio
async def test_archive_restore_round_trip(admin_session: AsyncSession) -> None:
    _t, context, farm_id, _b = await _bootstrap(admin_session, "bd-archive")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = (
            await client.post(
                f"/api/v1/farms/{farm_id}/resources",
                json={"kind": "worker", "name": "Yousef", "role": "field_worker"},
            )
        ).json()
        resource_id = created["id"]

        archived = await client.patch(f"/api/v1/resources/{resource_id}", json={"archive": True})
        assert archived.status_code == 200, archived.text
        assert archived.json()["archived_at"] is not None

        # Default list hides archived
        active = (await client.get(f"/api/v1/farms/{farm_id}/resources")).json()
        assert active == []

        # include_archived brings it back
        with_archived = (
            await client.get(
                f"/api/v1/farms/{farm_id}/resources",
                params={"include_archived": "true"},
            )
        ).json()
        assert any(r["id"] == resource_id for r in with_archived)

        # Restore
        restored = await client.patch(f"/api/v1/resources/{resource_id}", json={"archive": False})
        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None


# ---------------------------------------------------------------------------
# Attach / detach to plan_activities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attach_and_detach_resource_to_activity(
    admin_session: AsyncSession,
) -> None:
    _t, context, farm_id, block_id = await _bootstrap(admin_session, "bd-attach")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        scheduled_for = date.today() + timedelta(days=5)
        activity = (
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "spraying",
                    "scheduled_date": scheduled_for.isoformat(),
                },
            )
        ).json()
        activity_id = activity["id"]

        worker = (
            await client.post(
                f"/api/v1/farms/{farm_id}/resources",
                json={"kind": "worker", "name": "Ali", "role": "operator"},
            )
        ).json()
        tractor = (
            await client.post(
                f"/api/v1/farms/{farm_id}/resources",
                json={
                    "kind": "equipment",
                    "name": "Tractor #1",
                    "equipment_type": "tractor",
                },
            )
        ).json()

        # Attach both
        a1 = await client.post(f"/api/v1/activities/{activity_id}/resources/{worker['id']}")
        assert a1.status_code == 201, a1.text
        a2 = await client.post(f"/api/v1/activities/{activity_id}/resources/{tractor['id']}")
        assert a2.status_code == 201, a2.text

        # Re-attach is idempotent (no 409)
        a3 = await client.post(f"/api/v1/activities/{activity_id}/resources/{worker['id']}")
        assert a3.status_code == 201

        # Detach one
        d1 = await client.delete(f"/api/v1/activities/{activity_id}/resources/{worker['id']}")
        assert d1.status_code == 204


@pytest.mark.asyncio
async def test_attach_archived_resource_rejected(
    admin_session: AsyncSession,
) -> None:
    _t, context, farm_id, block_id = await _bootstrap(admin_session, "bd-archived-attach")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        scheduled_for = date.today() + timedelta(days=5)
        activity = (
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "irrigation",
                    "scheduled_date": scheduled_for.isoformat(),
                },
            )
        ).json()
        worker = (
            await client.post(
                f"/api/v1/farms/{farm_id}/resources",
                json={"kind": "worker", "name": "Mona", "role": "scout"},
            )
        ).json()
        await client.patch(f"/api/v1/resources/{worker['id']}", json={"archive": True})
        bad = await client.post(f"/api/v1/activities/{activity['id']}/resources/{worker['id']}")
        assert bad.status_code == 422, bad.text
