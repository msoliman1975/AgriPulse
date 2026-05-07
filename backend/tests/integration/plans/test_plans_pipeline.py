"""Integration tests for vegetation_plans + plan_activities (PR-6).

Covers:
  * Plan CRUD + season-uniqueness conflict
  * Activity CRUD + state machine (scheduled → in_progress → completed)
  * Calendar query joining activities → plan filtered by farm + date
  * RBAC: Viewer can read, FieldOperator can complete but not create,
    plan.manage required for metadata edits.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import install_exception_handlers
from app.modules.farms.router import router as farms_router
from app.modules.plans.router import router as plans_router
from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole
from tests.integration.farms.conftest import StubAuth, make_context
from tests.integration.farms.test_blocks_unit_type import _polygon
from tests.integration.farms.test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _build_app(context) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(farms_router)
    app.include_router(plans_router)
    app.add_middleware(StubAuth, context=context)
    return app


async def _bootstrap(admin_session: AsyncSession, slug: str) -> tuple[object, object, str, str]:
    """Tenant + admin user + farm + block. Returns
    (tenant, request_context, farm_id, block_id)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"PR-6 {slug}",
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
                "code": "PR6-FARM",
                "name": "PR-6 Farm",
                "boundary": _square(31.20, 30.10),
                "farm_type": "commercial",
                "tags": [],
            },
        )
        assert farm_resp.status_code == 201, farm_resp.text
        farm_id = farm_resp.json()["id"]
        block_resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": "PR6-B1", "boundary": _polygon(31.21, 30.11)},
        )
        assert block_resp.status_code == 201, block_resp.text
        block_id = block_resp.json()["id"]
    return tenant, context, farm_id, block_id


# ---------------------------------------------------------------------------
# Plan CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_crud_round_trip(admin_session: AsyncSession) -> None:
    _tenant, context, farm_id, _block_id = await _bootstrap(admin_session, "pr6-plan-crud")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/farms/{farm_id}/plans",
            json={
                "season_label": "2026-summer",
                "season_year": 2026,
                "name": "Summer 2026",
                "notes": "draft schedule",
            },
        )
        assert created.status_code == 201, created.text
        plan_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        # Duplicate season → 409.
        dup = await client.post(
            f"/api/v1/farms/{farm_id}/plans",
            json={"season_label": "2026-summer", "season_year": 2026},
        )
        assert dup.status_code == 409, dup.text

        # PATCH activate.
        patched = await client.patch(f"/api/v1/plans/{plan_id}", json={"status": "active"})
        assert patched.status_code == 200
        assert patched.json()["status"] == "active"

        # GET list.
        listed = await client.get(f"/api/v1/farms/{farm_id}/plans")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        # DELETE archives — list now empty by default.
        deleted = await client.delete(f"/api/v1/plans/{plan_id}")
        assert deleted.status_code == 204
        listed_after = await client.get(f"/api/v1/farms/{farm_id}/plans")
        assert listed_after.json() == []

        # include_archived=true brings it back.
        with_archived = await client.get(
            f"/api/v1/farms/{farm_id}/plans", params={"include_archived": "true"}
        )
        assert any(p["id"] == plan_id for p in with_archived.json())


# ---------------------------------------------------------------------------
# Activity CRUD + state machine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_state_machine(admin_session: AsyncSession) -> None:
    _tenant, context, farm_id, block_id = await _bootstrap(admin_session, "pr6-activity")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        plan_id = plan["id"]

        scheduled_for = date.today() + timedelta(days=14)
        created = await client.post(
            f"/api/v1/plans/{plan_id}/activities",
            json={
                "block_id": block_id,
                "activity_type": "spraying",
                "scheduled_date": scheduled_for.isoformat(),
                "product_name": "Mancozeb 75% WP",
                "dosage": "2.5 L/ha",
                "notes": "preventive treatment",
            },
        )
        assert created.status_code == 201, created.text
        activity_id = created.json()["id"]
        assert created.json()["status"] == "scheduled"

        # scheduled → in_progress
        started = await client.patch(f"/api/v1/activities/{activity_id}", json={"state": "start"})
        assert started.status_code == 200
        assert started.json()["status"] == "in_progress"

        # in_progress → completed (stamps completed_at + completed_by)
        completed = await client.patch(
            f"/api/v1/activities/{activity_id}", json={"state": "complete"}
        )
        assert completed.status_code == 200
        body = completed.json()
        assert body["status"] == "completed"
        assert body["completed_at"] is not None
        assert body["completed_by"] is not None

        # completed → start is rejected (409).
        rejected = await client.patch(f"/api/v1/activities/{activity_id}", json={"state": "start"})
        assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_activity_skip_terminal(admin_session: AsyncSession) -> None:
    _tenant, context, farm_id, block_id = await _bootstrap(admin_session, "pr6-activity-skip")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        activity = (
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "fertilizing",
                    "scheduled_date": date.today().isoformat(),
                },
            )
        ).json()

        skip = await client.patch(f"/api/v1/activities/{activity['id']}", json={"state": "skip"})
        assert skip.status_code == 200
        assert skip.json()["status"] == "skipped"

        # skipped → complete is rejected.
        rejected = await client.patch(
            f"/api/v1/activities/{activity['id']}", json={"state": "complete"}
        )
        assert rejected.status_code == 409


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_filters_by_date_range(admin_session: AsyncSession) -> None:
    _tenant, context, farm_id, block_id = await _bootstrap(admin_session, "pr6-calendar")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        anchor = date.today()
        for offset, kind in ((0, "spraying"), (5, "fertilizing"), (40, "harvesting")):
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": kind,
                    "scheduled_date": (anchor + timedelta(days=offset)).isoformat(),
                },
            )

        listed = await client.get(
            f"/api/v1/farms/{farm_id}/plans/calendar",
            params={
                "from": anchor.isoformat(),
                "to": (anchor + timedelta(days=30)).isoformat(),
            },
        )
        assert listed.status_code == 200
        # The 40-day-out harvesting activity falls outside the window.
        types = sorted(a["activity_type"] for a in listed.json()["activities"])
        assert types == ["fertilizing", "spraying"]


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_cannot_create_or_complete(admin_session: AsyncSession) -> None:
    tenant, _admin_ctx, farm_id, block_id = await _bootstrap(admin_session, "pr6-rbac-viewer")

    # Set up a plan + activity as TenantAdmin so the Viewer has
    # something to read.
    admin_app = _build_app(_admin_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://test"
    ) as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        activity = (
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "spraying",
                    "scheduled_date": date.today().isoformat(),
                },
            )
        ).json()

    viewer_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=viewer_id)
    viewer_ctx = make_context(
        user_id=viewer_id,
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.VIEWER),),
    )
    viewer_app = _build_app(viewer_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=viewer_app), base_url="http://test"
    ) as client:
        # Viewer can read.
        listed = await client.get(f"/api/v1/farms/{farm_id}/plans")
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1

        # Viewer cannot create plans. The route uses requires_capability,
        # which returns 403; the user already has farm.read so there's
        # no existence leak to hide.
        create = await client.post(
            f"/api/v1/farms/{farm_id}/plans",
            json={"season_label": "2026-fall", "season_year": 2026},
        )
        assert create.status_code == 403, create.text

        # Viewer cannot complete activities.
        complete = await client.patch(
            f"/api/v1/activities/{activity['id']}", json={"state": "complete"}
        )
        assert complete.status_code == 404, complete.text


@pytest.mark.asyncio
async def test_field_operator_can_complete_but_not_edit_metadata(
    admin_session: AsyncSession,
) -> None:
    tenant, _admin_ctx, farm_id, block_id = await _bootstrap(admin_session, "pr6-rbac-fieldop")

    admin_app = _build_app(_admin_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://test"
    ) as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        activity = (
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "spraying",
                    "scheduled_date": date.today().isoformat(),
                },
            )
        ).json()

    op_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=op_id)
    op_ctx = make_context(
        user_id=op_id,
        tenant_id=tenant.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.FIELD_OPERATOR),),
    )
    op_app = _build_app(op_ctx)
    async with AsyncClient(transport=ASGITransport(app=op_app), base_url="http://test") as client:
        # FieldOperator can complete.
        completed = await client.patch(
            f"/api/v1/activities/{activity['id']}", json={"state": "complete"}
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"

    # But editing metadata only is rejected (separate request after the
    # completion above leaves status terminal — pick a fresh activity).
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://test"
    ) as client:
        another = (
            await client.post(
                f"/api/v1/plans/{plan['id']}/activities",
                json={
                    "block_id": block_id,
                    "activity_type": "fertilizing",
                    "scheduled_date": date.today().isoformat(),
                },
            )
        ).json()

    async with AsyncClient(transport=ASGITransport(app=op_app), base_url="http://test") as client:
        edit = await client.patch(
            f"/api/v1/activities/{another['id']}",
            json={"product_name": "FieldOp wants to change the product"},
        )
        assert edit.status_code == 404, edit.text


# ---------------------------------------------------------------------------
# duration_days + start_time (PR-1 of UX slice — added 2026-05-07)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activity_duration_and_start_time_round_trip(admin_session: AsyncSession) -> None:
    _tenant, context, farm_id, block_id = await _bootstrap(admin_session, "pr1-duration")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plan = (
            await client.post(
                f"/api/v1/farms/{farm_id}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()

        # Create with explicit duration_days + start_time.
        created = await client.post(
            f"/api/v1/plans/{plan['id']}/activities",
            json={
                "block_id": block_id,
                "activity_type": "spraying",
                "scheduled_date": date.today().isoformat(),
                "duration_days": 3,
                "start_time": "06:00",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["duration_days"] == 3
        assert body["start_time"] == "06:00:00"

        # Default duration_days=1, start_time=null.
        defaulted = await client.post(
            f"/api/v1/plans/{plan['id']}/activities",
            json={
                "block_id": block_id,
                "activity_type": "fertilizing",
                "scheduled_date": date.today().isoformat(),
            },
        )
        assert defaulted.status_code == 201
        assert defaulted.json()["duration_days"] == 1
        assert defaulted.json()["start_time"] is None

        # PATCH duration_days bump.
        patched = await client.patch(
            f"/api/v1/activities/{body['id']}",
            json={"duration_days": 5, "start_time": "14:30"},
        )
        assert patched.status_code == 200
        assert patched.json()["duration_days"] == 5
        assert patched.json()["start_time"] == "14:30:00"

        # Out-of-range duration → 422.
        bad = await client.post(
            f"/api/v1/plans/{plan['id']}/activities",
            json={
                "block_id": block_id,
                "activity_type": "spraying",
                "scheduled_date": date.today().isoformat(),
                "duration_days": 100,
            },
        )
        assert bad.status_code == 422, bad.text

        # Calendar surfaces the new fields.
        cal = await client.get(
            f"/api/v1/farms/{farm_id}/plans/calendar",
            params={
                "from": date.today().isoformat(),
                "to": (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        assert cal.status_code == 200
        for item in cal.json()["activities"]:
            assert "duration_days" in item
            assert "start_time" in item
