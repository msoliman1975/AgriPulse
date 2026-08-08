"""Integration tests: Tenant Settings → Bulk Updates → crop assignment.

Covers the three endpoints as a set — candidates feeds the picker, preview
promises an outcome per block, apply delivers it. The promise is the point:
the last test here is the one that would catch a preview and an apply drifting
apart.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import FarmRole, FarmScope, TenantRole

from .conftest import build_app, make_context

pytestmark = [pytest.mark.integration]


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


def _multipolygon(lon: float, lat: float, side: float = 0.05) -> dict[str, object]:
    return {"type": "MultiPolygon", "coordinates": [_polygon(lon, lat, side)["coordinates"]]}


async def _seed_tenant(admin_session: AsyncSession, slug: str) -> tuple[Any, Any]:
    """Tenant + user + TenantAdmin membership. Returns (tenant, user_id)."""
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(slug=slug, name=slug, contact_email=f"ops@{slug}.test")
    user_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.users (id, keycloak_subject, email, full_name) "
            "VALUES (:id, :sub, :email, :name)"
        ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
        {"id": user_id, "sub": f"kc-{user_id}", "email": f"u@{slug}.test", "name": "U"},
    )
    membership_id = uuid4()
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_memberships (id, user_id, tenant_id, status) "
            "VALUES (:mid, :uid, :tid, 'active')"
        ).bindparams(
            bindparam("mid", type_=PG_UUID(as_uuid=True)),
            bindparam("uid", type_=PG_UUID(as_uuid=True)),
            bindparam("tid", type_=PG_UUID(as_uuid=True)),
        ),
        {"mid": membership_id, "uid": user_id, "tid": tenant.tenant_id},
    )
    await admin_session.execute(
        text(
            "INSERT INTO public.tenant_role_assignments (membership_id, role) "
            "VALUES (:mid, 'TenantAdmin')"
        ).bindparams(bindparam("mid", type_=PG_UUID(as_uuid=True))),
        {"mid": membership_id},
    )
    await admin_session.commit()
    return tenant, user_id


async def _crop_id(admin_session: AsyncSession, code: str = "wheat") -> Any:
    return (
        await admin_session.execute(
            text("SELECT id FROM public.crops WHERE code = :c"), {"c": code}
        )
    ).scalar_one()


async def _farm_with_blocks(client: AsyncClient, codes: list[str]) -> tuple[str, dict[str, str]]:
    """Create a farm and one block per code. Returns (farm_id, {code: block_id})."""
    farm = await client.post(
        "/api/v1/farms",
        json={"code": "BULK", "name": "Bulk Farm", "boundary": _multipolygon(31.2, 30.0)},
    )
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]

    blocks: dict[str, str] = {}
    for i, code in enumerate(codes):
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            # Spread the polygons so they never touch — overlapping AOIs are a
            # different rejection and would mask what these tests assert.
            json={"code": code, "boundary": _polygon(31.2 + i * 0.01, 30.0)},
        )
        assert resp.status_code == 201, resp.text
        blocks[code] = resp.json()["id"]
    return farm_id, blocks


@pytest.mark.asyncio
async def test_candidates_report_the_crop_each_block_holds(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-cand")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2", "B3"])
        assigned = await c.post(
            f"/api/v1/blocks/{blocks['B2']}/crop-assignments",
            json={"crop_id": str(crop), "season_label": "2026A", "make_current": True},
        )
        assert assigned.status_code == 201

        resp = await c.get(f"/api/v1/farms/{farm_id}/bulk/crop-assignment/candidates")
        assert resp.status_code == 200, resp.text
        rows = {r["code"]: r for r in resp.json()}

        assert set(rows) == {"B1", "B2", "B3"}
        assert rows["B1"]["current"] is None
        assert rows["B3"]["current"] is None
        assert rows["B2"]["current"]["season_label"] == "2026A"
        assert rows["B2"]["current"]["crop_path"] == "wheat"
        # The picker's sortable columns read these; a null area would render
        # an empty column rather than an obvious error.
        assert rows["B1"]["area_value"] is not None
        assert rows["B1"]["area_unit"]


def _bulk_body(crop: Any, block_ids: list[str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "crop_id": str(crop),
        "season_label": "2027A",
        "conflict_mode": "skip",
        "targets": [{"block_id": b} for b in block_ids],
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_preview_skip_mode_leaves_assigned_blocks_alone(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-prev-skip")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2"])
        await c.post(
            f"/api/v1/blocks/{blocks['B2']}/crop-assignments",
            json={"crop_id": str(crop), "season_label": "2026A", "make_current": True},
        )

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment:preview",
            json=_bulk_body(crop, [blocks["B1"], blocks["B2"]]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["assign_count"], body["replace_count"], body["skip_count"]) == (1, 0, 1)
        by_code = {i["code"]: i for i in body["items"]}
        assert by_code["B1"]["outcome"] == "assign"
        assert by_code["B1"]["after"]["season_label"] == "2027A"
        assert by_code["B2"]["outcome"] == "skip"
        assert by_code["B2"]["after"] is None
        # The reason is rendered verbatim in the results table.
        assert "2026A" in by_code["B2"]["detail"]

        # Preview must not have written anything.
        listing = await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")
        assert listing.json() == []


@pytest.mark.asyncio
async def test_preview_replace_mode_marks_the_assigned_block_for_replacement(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-prev-rep")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2"])
        await c.post(
            f"/api/v1/blocks/{blocks['B2']}/crop-assignments",
            json={"crop_id": str(crop), "season_label": "2026A", "make_current": True},
        )

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment:preview",
            json=_bulk_body(crop, [blocks["B1"], blocks["B2"]], conflict_mode="replace"),
        )
        body = resp.json()
        assert (body["assign_count"], body["replace_count"], body["skip_count"]) == (1, 1, 0)
        by_code = {i["code"]: i for i in body["items"]}
        assert by_code["B2"]["outcome"] == "replace"
        assert by_code["B2"]["before"]["season_label"] == "2026A"
        assert by_code["B2"]["after"]["season_label"] == "2027A"


@pytest.mark.asyncio
async def test_apply_writes_the_crop_and_reports_each_block(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-apply")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2", "B3"])
        await c.post(
            f"/api/v1/blocks/{blocks['B3']}/crop-assignments",
            json={"crop_id": str(crop), "season_label": "2026A", "make_current": True},
        )

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json=_bulk_body(crop, [blocks["B1"], blocks["B2"], blocks["B3"]]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["applied_count"], body["skipped_count"], body["failed_count"]) == (2, 1, 0)

        by_code = {i["code"]: i for i in body["items"]}
        assert by_code["B1"]["outcome"] == "assigned"
        assert by_code["B1"]["block_crop_id"]
        assert by_code["B3"]["outcome"] == "skipped"
        assert by_code["B3"]["block_crop_id"] is None

        # The write really landed, and B3 kept its old season.
        for code in ("B1", "B2"):
            rows = (await c.get(f"/api/v1/blocks/{blocks[code]}/crop-assignments")).json()
            assert [r["season_label"] for r in rows] == ["2027A"]
            assert rows[0]["is_active_now"] is True
        b3 = (await c.get(f"/api/v1/blocks/{blocks['B3']}/crop-assignments")).json()
        assert [r["season_label"] for r in b3] == ["2026A"]


@pytest.mark.asyncio
async def test_replace_mode_closes_the_previous_assignment(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-replace")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    start = date.today() + timedelta(days=10)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        await c.post(
            f"/api/v1/blocks/{blocks['B1']}/crop-assignments",
            json={"crop_id": str(crop), "season_label": "2026A", "make_current": True},
        )

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json=_bulk_body(
                crop,
                [blocks["B1"]],
                conflict_mode="replace",
                effective_from=start.isoformat(),
            ),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["items"][0]["outcome"] == "replaced"

        rows = (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json()
        by_season = {r["season_label"]: r for r in rows}
        assert len(rows) == 2
        # History is kept: the old one is closed exactly where the new starts,
        # so there is neither a gap nor an overlap between them.
        assert by_season["2026A"]["effective_to"] == start.isoformat()
        assert by_season["2027A"]["effective_from"] == start.isoformat()
        assert by_season["2027A"]["effective_to"] is None


@pytest.mark.asyncio
async def test_per_block_overrides_beat_the_shared_values(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-override")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    shared_planting = date.today() - timedelta(days=5)
    block_planting = date.today() - timedelta(days=2)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2"])
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json={
                "crop_id": str(crop),
                "season_label": "2027A",
                "planting_date": shared_planting.isoformat(),
                "conflict_mode": "skip",
                "targets": [
                    {"block_id": blocks["B1"]},
                    {
                        "block_id": blocks["B2"],
                        "season_label": "2027B",
                        "planting_date": block_planting.isoformat(),
                    },
                ],
            },
        )
        assert resp.status_code == 200, resp.text
        by_code = {i["code"]: i for i in resp.json()["items"]}
        assert by_code["B1"]["overridden"] is False
        assert by_code["B2"]["overridden"] is True

        b1 = (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json()[0]
        b2 = (await c.get(f"/api/v1/blocks/{blocks['B2']}/crop-assignments")).json()[0]
        assert b1["season_label"] == "2027A"
        assert b1["planting_date"] == shared_planting.isoformat()
        assert b2["season_label"] == "2027B"
        assert b2["planting_date"] == block_planting.isoformat()
        # An overridden planting date moves that block's validity start too,
        # exactly as assigning it alone would.
        assert b2["effective_from"] == block_planting.isoformat()


@pytest.mark.asyncio
async def test_one_failing_block_does_not_take_down_the_run(
    admin_session: AsyncSession,
) -> None:
    """A block with a *scheduled* future assignment overlaps the new ongoing
    one. Without a SAVEPOINT per block that error aborts the transaction and
    every later block fails with "current transaction is aborted" instead of
    its own reason.
    """
    tenant, user_id = await _seed_tenant(admin_session, "bulk-partial")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    future = date.today() + timedelta(days=90)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2", "B3"])
        # B2 gets an assignment that starts in the future: not current today,
        # so the plan says "assign", but the insert collides with its range.
        scheduled = await c.post(
            f"/api/v1/blocks/{blocks['B2']}/crop-assignments",
            json={
                "crop_id": str(crop),
                "season_label": "2028A",
                "effective_from": future.isoformat(),
                "make_current": False,
            },
        )
        assert scheduled.status_code == 201, scheduled.text

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json=_bulk_body(crop, [blocks["B1"], blocks["B2"], blocks["B3"]]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["applied_count"], body["skipped_count"], body["failed_count"]) == (2, 0, 1)

        by_code = {i["code"]: i for i in body["items"]}
        assert by_code["B2"]["outcome"] == "failed"
        assert by_code["B2"]["detail"]
        # B3 comes *after* the failure in target order — this is the assertion
        # that fails if the savepoint is dropped.
        assert by_code["B3"]["outcome"] == "assigned"

        for code in ("B1", "B3"):
            rows = (await c.get(f"/api/v1/blocks/{blocks[code]}/crop-assignments")).json()
            assert [r["season_label"] for r in rows] == ["2027A"]
        # The failed block kept only its scheduled row — nothing half-written.
        b2 = (await c.get(f"/api/v1/blocks/{blocks['B2']}/crop-assignments")).json()
        assert [r["season_label"] for r in b2] == ["2028A"]


@pytest.mark.asyncio
async def test_preview_and_apply_agree_on_every_block(
    admin_session: AsyncSession,
) -> None:
    """The contract the whole surface rests on: what the dry run showed is what
    the apply did. Preview verbs are future tense, apply verbs past tense."""
    tenant, user_id = await _seed_tenant(admin_session, "bulk-agree")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    expected = {"assign": "assigned", "replace": "replaced", "skip": "skipped"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2", "B3"])
        await c.post(
            f"/api/v1/blocks/{blocks['B3']}/crop-assignments",
            json={"crop_id": str(crop), "season_label": "2026A", "make_current": True},
        )
        body = _bulk_body(crop, [blocks["B1"], blocks["B2"], blocks["B3"]])

        preview = (
            await c.post(f"/api/v1/farms/{farm_id}/bulk/crop-assignment:preview", json=body)
        ).json()
        applied = (await c.post(f"/api/v1/farms/{farm_id}/bulk/crop-assignment", json=body)).json()

        pv = {i["code"]: i for i in preview["items"]}
        ap = {i["code"]: i for i in applied["items"]}
        assert set(pv) == set(ap)
        for code, item in pv.items():
            assert ap[code]["outcome"] == expected[item["outcome"]], code
            assert ap[code]["after"] == item["after"], code
        assert applied["applied_count"] == preview["assign_count"] + preview["replace_count"]
        assert applied["skipped_count"] == preview["skip_count"]


@pytest.mark.asyncio
async def test_targets_outside_the_farm_are_never_written(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-foreign")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        stranger = uuid4()

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json=_bulk_body(crop, [blocks["B1"], str(stranger)]),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["applied_count"], body["failed_count"]) == (1, 0)
        foreign = next(i for i in body["items"] if i["block_id"] == str(stranger))
        assert foreign["outcome"] == "skipped"
        assert "not an active block" in (foreign["detail"] or "").lower()


@pytest.mark.asyncio
async def test_duplicate_targets_are_rejected(admin_session: AsyncSession) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "bulk-dup")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json=_bulk_body(crop, [blocks["B1"], blocks["B1"]]),
        )
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_farm_viewer_cannot_run_a_bulk_assignment(admin_session: AsyncSession) -> None:
    """`crop_assignment.create` gates the bulk routes exactly as it gates the
    single-block one — doing a write forty times is not a lesser permission."""
    tenant, user_id = await _seed_tenant(admin_session, "bulk-rbac")
    crop = await _crop_id(admin_session)
    admin_app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])

    viewer_app = build_app(
        make_context(
            user_id=user_id,
            tenant_id=tenant.tenant_id,
            farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=FarmRole.VIEWER),),
        )
    )
    async with AsyncClient(transport=ASGITransport(app=viewer_app), base_url="http://test") as c:
        assert (
            await c.get(f"/api/v1/farms/{farm_id}/bulk/crop-assignment/candidates")
        ).status_code in (403, 404)
        assert (
            await c.post(
                f"/api/v1/farms/{farm_id}/bulk/crop-assignment:preview",
                json=_bulk_body(crop, [blocks["B1"]]),
            )
        ).status_code in (403, 404)
        assert (
            await c.post(
                f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
                json=_bulk_body(crop, [blocks["B1"]]),
            )
        ).status_code in (403, 404)

    # Nothing was written by the attempts.
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        assert (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json() == []
