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
                "role": "Agronomist",
                "phone": "+201112233445",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["kind"] == "worker"
        assert body["name"] == "Ahmed Hassan"  # trimmed
        assert body["role"] == "Agronomist"
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
            json={"name": "Ahmed H.", "role": "Scout"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "Ahmed H."
        assert patched.json()["role"] == "Scout"


@pytest.mark.asyncio
async def test_worker_membership_link_round_trip(admin_session: AsyncSession) -> None:
    """U-3: a worker can be linked to a member, unlinked, and re-linked.

    The link is a cross-schema logical reference (no FK), so any membership
    UUID round-trips at this layer — we assert the plumbing, not referential
    integrity. Equipment must reject a membership link (kind-shape rule).
    """
    _t, context, farm_id, _b = await _bootstrap(admin_session, "bd-link")
    app = _build_app(context)
    membership_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "worker",
                "name": "Salma",
                "role": "Agronomist",
                "membership_id": membership_id,
            },
        )
        assert created.status_code == 201, created.text
        resource_id = created.json()["id"]
        assert created.json()["membership_id"] == membership_id

        # Explicit null unlinks.
        unlinked = await client.patch(
            f"/api/v1/resources/{resource_id}", json={"membership_id": None}
        )
        assert unlinked.status_code == 200, unlinked.text
        assert unlinked.json()["membership_id"] is None

        # Re-link.
        relinked = await client.patch(
            f"/api/v1/resources/{resource_id}", json={"membership_id": membership_id}
        )
        assert relinked.status_code == 200, relinked.text
        assert relinked.json()["membership_id"] == membership_id

        # Equipment cannot be linked to a member.
        bad = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={
                "kind": "equipment",
                "name": "Tractor #9",
                "equipment_type": "tractor",
                "membership_id": membership_id,
            },
        )
        assert bad.status_code == 422, bad.text


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
                "role": "FieldOperator",
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
            json={"kind": "worker", "name": "Khalid", "role": "FieldOperator"},
        )
        assert first.status_code == 201

        # Same case
        dup = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "worker", "name": "Khalid", "role": "FieldOperator"},
        )
        assert dup.status_code == 409, dup.text

        # Different case still rejected (uq on lower(name))
        dup_case = await client.post(
            f"/api/v1/farms/{farm_id}/resources",
            json={"kind": "worker", "name": "khalid", "role": "FieldOperator"},
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
                json={"kind": "worker", "name": "Yousef", "role": "FieldWorker"},
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
                json={"kind": "worker", "name": "Ali", "role": "FieldOperator"},
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
                json={"kind": "worker", "name": "Mona", "role": "Scout"},
            )
        ).json()
        await client.patch(f"/api/v1/resources/{worker['id']}", json={"archive": True})
        bad = await client.post(f"/api/v1/activities/{activity['id']}/resources/{worker['id']}")
        assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_resource_cannot_be_assigned_to_a_farm_it_does_not_serve(
    admin_session: AsyncSession,
) -> None:
    """W2-B — the guard that `resources.farm_id` used to make unnecessary.

    While a resource was farm-locked this was structurally impossible. Now
    that the roster is tenant-level, the only thing standing between a shared
    worker and being scheduled somewhere their sign-in does not reach is an
    explicit check against the availability set.
    """
    _t, context, farm_a, block_a = await _bootstrap(admin_session, "bd-avail")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # A second farm, with an activity of its own.
        farm_b = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "BD-FARM-B",
                    "name": "Other board farm",
                    "boundary": _square(31.80, 30.80),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()["id"]
        block_b = (
            await client.post(
                f"/api/v1/farms/{farm_b}/blocks",
                json={"code": "BD-B2", "boundary": _polygon(31.81, 30.81)},
            )
        ).json()["id"]
        plan_b = (
            await client.post(
                f"/api/v1/farms/{farm_b}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        activity_b = (
            await client.post(
                f"/api/v1/plans/{plan_b['id']}/activities",
                json={
                    "block_id": block_b,
                    "activity_type": "spraying",
                    "scheduled_date": (date.today() + timedelta(days=3)).isoformat(),
                },
            )
        ).json()["id"]

        # A worker who serves only farm A.
        worker = (
            await client.post(
                f"/api/v1/farms/{farm_a}/resources",
                json={"kind": "worker", "name": "Farm A Only", "role": "FieldOperator"},
            )
        ).json()

        refused = await client.post(f"/api/v1/activities/{activity_b}/resources/{worker['id']}")
        assert refused.status_code == 409, refused.text
        assert "not available on the farm" in refused.json()["detail"]

        # They are not silently listed on farm B either.
        listed_b = (await client.get(f"/api/v1/farms/{farm_b}/resources")).json()
        assert worker["id"] not in {r["id"] for r in listed_b}

        # And the same assignment on their own farm still works.
        plan_a = (
            await client.post(
                f"/api/v1/farms/{farm_a}/plans",
                json={"season_label": "2026-summer", "season_year": 2026},
            )
        ).json()
        activity_a = (
            await client.post(
                f"/api/v1/plans/{plan_a['id']}/activities",
                json={
                    "block_id": block_a,
                    "activity_type": "spraying",
                    "scheduled_date": (date.today() + timedelta(days=4)).isoformat(),
                },
            )
        ).json()["id"]
        ok = await client.post(f"/api/v1/activities/{activity_a}/resources/{worker['id']}")
        assert ok.status_code in (200, 201), ok.text


@pytest.mark.asyncio
async def test_a_farm_manager_cannot_rename_a_worker_shared_with_another_farm(
    admin_session: AsyncSession,
) -> None:
    """W2-B — the authorization split, and the failure mode it exists for.

    Name, phone, role and archived state are one row shared by every farm the
    resource serves. A farm-A manager editing them is rewriting farm B's data,
    so the strict side of the split requires the capability on *every* farm in
    the availability set. Reading only needs one.
    """
    from uuid import UUID as _UUID

    from app.shared.auth.context import FarmRole, FarmScope

    _t, admin_ctx, farm_a, _b = await _bootstrap(admin_session, "bd-authz")
    admin_app = _build_app(admin_ctx)
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://test"
    ) as client:
        farm_b = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "BD-AUTHZ-B",
                    "name": "Authz farm B",
                    "boundary": _square(31.95, 30.95),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()["id"]
        shared = (
            await client.post(
                f"/api/v1/farms/{farm_a}/resources",
                json={"kind": "worker", "name": "Shared Salma", "role": "FieldOperator"},
            )
        ).json()
        # Lend them to farm B as well.
        both = await client.put(
            f"/api/v1/resources/{shared['id']}/farms",
            json={"farm_ids": [farm_a, farm_b]},
        )
        assert both.status_code == 200, both.text
        assert set(both.json()) == {farm_a, farm_b}

    # A manager of farm A only — no tenant role at all.
    a_only = make_context(
        user_id=uuid4(),
        tenant_id=admin_ctx.tenant_id,
        tenant_role=None,
        farm_scopes=(FarmScope(farm_id=_UUID(farm_a), role=FarmRole.FARM_MANAGER),),
    )
    async with AsyncClient(
        transport=ASGITransport(app=_build_app(a_only)), base_url="http://test"
    ) as client:
        # Reading is fine: they manage one of the farms this person serves.
        readable = await client.get(f"/api/v1/resources/{shared['id']}")
        assert readable.status_code == 200, readable.text

        # Renaming is not — farm B would silently get a different worker.
        renamed = await client.patch(
            f"/api/v1/resources/{shared['id']}", json={"name": "Renamed By A"}
        )
        assert renamed.status_code == 404, renamed.text

        # Nor can they quietly drop farm B from the availability set.
        dropped = await client.put(
            f"/api/v1/resources/{shared['id']}/farms", json={"farm_ids": [farm_a]}
        )
        assert dropped.status_code == 404, dropped.text

    # The name really did not change.
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://test"
    ) as client:
        assert (await client.get(f"/api/v1/resources/{shared['id']}")).json()[
            "name"
        ] == "Shared Salma"

        # And a worker on farm A alone is still editable by farm A's manager.
        solo = (
            await client.post(
                f"/api/v1/farms/{farm_a}/resources",
                json={"kind": "worker", "name": "Solo Samir", "role": "FieldOperator"},
            )
        ).json()
    async with AsyncClient(
        transport=ASGITransport(app=_build_app(a_only)), base_url="http://test"
    ) as client:
        ok = await client.patch(f"/api/v1/resources/{solo['id']}", json={"name": "Renamed Fine"})
        assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_tenant_roster_lists_every_farm_and_its_availability(
    admin_session: AsyncSession,
) -> None:
    """The read the People page is built on: one row per person, carrying
    where they can work — not one row per person per farm."""
    _t, context, farm_a, _b = await _bootstrap(admin_session, "bd-roster")
    app = _build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_b = (
            await client.post(
                "/api/v1/farms",
                json={
                    "code": "BD-ROSTER-B",
                    "name": "Roster farm B",
                    "boundary": _square(32.05, 31.05),
                    "farm_type": "commercial",
                    "tags": [],
                },
            )
        ).json()["id"]
        worker = (
            await client.post(
                f"/api/v1/farms/{farm_a}/resources",
                json={"kind": "worker", "name": "Roaming Rami", "role": "FieldOperator"},
            )
        ).json()
        await client.put(
            f"/api/v1/resources/{worker['id']}/farms",
            json={"farm_ids": [farm_a, farm_b]},
        )

        roster = await client.get("/api/v1/resources")
        assert roster.status_code == 200, roster.text
        rows = {r["id"]: r for r in roster.json()}
        # One row, not two — which is the entire point of the promotion.
        assert list(rows).count(worker["id"]) == 1
        assert set(rows[worker["id"]]["farm_ids"]) == {farm_a, farm_b}

        # And they show up on both farms' per-farm lists.
        for farm in (farm_a, farm_b):
            listed = (await client.get(f"/api/v1/farms/{farm}/resources")).json()
            assert worker["id"] in {r["id"] for r in listed}
