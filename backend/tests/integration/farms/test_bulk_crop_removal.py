"""Integration tests: permanently removing crop assignments.

This is a HARD delete with no undo, so the tests care about two things above
all: that the preview tells the truth about what is destroyed, and that the
block is genuinely usable afterwards. The second is not obvious — the
`uq_block_crops_current` index is partial on `is_current = TRUE` and does NOT
exclude removed rows, so a removal that left the flag behind would make the
block permanently unable to take a new crop.
"""

from __future__ import annotations

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
    farm = await client.post(
        "/api/v1/farms",
        json={"code": "RM", "name": "Removal Farm", "boundary": _multipolygon(31.2, 30.0)},
    )
    assert farm.status_code == 201, farm.text
    farm_id = farm.json()["id"]
    blocks: dict[str, str] = {}
    for i, code in enumerate(codes):
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={"code": code, "boundary": _polygon(31.2 + i * 0.01, 30.0)},
        )
        assert resp.status_code == 201, resp.text
        blocks[code] = resp.json()["id"]
    return farm_id, blocks


async def _assign(
    client: AsyncClient, block_id: str, crop: Any, season: str, eff_from: str | None = None
) -> str:
    body: dict[str, Any] = {"crop_id": str(crop), "season_label": season, "make_current": True}
    if eff_from:
        body["effective_from"] = eff_from
    r = await client.post(f"/api/v1/blocks/{block_id}/crop-assignments", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


@pytest.mark.asyncio
async def test_preview_counts_everything_the_delete_would_destroy(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "rm-preview")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2"])
        # B1 gets two seasons; B2 stays empty so "nothing to remove" is covered.
        await _assign(c, blocks["B1"], crop, "2025A", "2025-01-01")
        await _assign(c, blocks["B1"], crop, "2026A", "2026-01-01")

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove-preview",
            json={"block_ids": [blocks["B1"], blocks["B2"]]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["assignment_count"] == 2
        assert body["block_count"] == 2

        by_code = {i["code"]: i for i in body["items"]}
        assert len(by_code["B1"]["assignments"]) == 2
        assert {a["season_label"] for a in by_code["B1"]["assignments"]} == {"2025A", "2026A"}
        # An empty block is reported, not omitted.
        assert by_code["B2"]["assignments"] == []
        assert "No crop assignments" in by_code["B2"]["detail"]

        # Preview must not have deleted anything.
        rows = (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json()
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_removal_really_deletes_and_cascades(admin_session: AsyncSession) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "rm-hard")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        bc_id = await _assign(c, blocks["B1"], crop, "2026A", "2026-01-01")
        # A growth-stage transition hangs off the assignment via ON DELETE CASCADE.
        stage = await c.post(
            f"/api/v1/blocks/{blocks['B1']}/growth-stages",
            json={"stage": "flowering", "source": "manual", "block_crop_id": bc_id},
        )
        assert stage.status_code in (200, 201), stage.text

        pre = (
            await c.post(
                f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove-preview",
                json={"block_ids": [blocks["B1"]]},
            )
        ).json()
        assert pre["growth_stage_log_count"] >= 1

        resp = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove",
            json={"block_ids": [blocks["B1"]]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["assignment_count"] == 1
        assert body["items"][0]["removed_count"] == 1

        # Gone, not merely hidden: a soft delete would also produce [] here,
        # so assert against the table too.
        assert (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json() == []
        schema = f"tenant_{str(tenant.tenant_id).replace('-', '')}"
        remaining = (
            await admin_session.execute(
                text(f'SELECT count(*) FROM "{schema}".block_crops WHERE id = :id').bindparams(
                    bindparam("id", type_=PG_UUID(as_uuid=True))
                ),
                {"id": UUID(bc_id)},
            )
        ).scalar_one()
        assert remaining == 0
        logs = (
            await admin_session.execute(
                text(
                    f'SELECT count(*) FROM "{schema}".growth_stage_logs WHERE block_crop_id = :id'
                ).bindparams(bindparam("id", type_=PG_UUID(as_uuid=True))),
                {"id": UUID(bc_id)},
            )
        ).scalar_one()
        assert logs == 0


@pytest.mark.asyncio
async def test_block_can_be_reassigned_after_removal(admin_session: AsyncSession) -> None:
    """The one that catches the `uq_block_crops_current` trap.

    That index is partial on `is_current = TRUE` and does not exclude removed
    rows, so any implementation that hid rows instead of deleting them would
    leave the block unable to take a new current crop.
    """
    tenant, user_id = await _seed_tenant(admin_session, "rm-reassign")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        await _assign(c, blocks["B1"], crop, "2026A", "2026-01-01")
        await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove",
            json={"block_ids": [blocks["B1"]]},
        )

        # Same dates the removed one occupied — proves the range is free too,
        # not just the current flag.
        again = await c.post(
            f"/api/v1/blocks/{blocks['B1']}/crop-assignments",
            json={
                "crop_id": str(crop),
                "season_label": "2026A-redo",
                "effective_from": "2026-01-01",
                "make_current": True,
            },
        )
        assert again.status_code == 201, again.text
        rows = (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json()
        assert [r["season_label"] for r in rows] == ["2026A-redo"]
        assert rows[0]["is_current"] is True


@pytest.mark.asyncio
async def test_undo_a_run_removes_only_its_own_assignments(
    admin_session: AsyncSession,
) -> None:
    """`block_crop_ids` is the surgical selector: a bulk run's undo must not
    take the block's earlier history with it."""
    tenant, user_id = await _seed_tenant(admin_session, "rm-undo")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1", "B2"])
        # Pre-existing history that the undo must NOT touch.
        await _assign(c, blocks["B1"], crop, "2024A", "2024-01-01")

        run = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment",
            json={
                "crop_id": str(crop),
                "season_label": "OOPS",
                "conflict_mode": "replace",
                "effective_from": "2026-01-01",
                "targets": [{"block_id": blocks["B1"]}, {"block_id": blocks["B2"]}],
            },
        )
        assert run.status_code == 200, run.text
        created = [i["block_crop_id"] for i in run.json()["items"] if i["block_crop_id"]]
        assert len(created) == 2

        undo = await c.post(
            f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove",
            json={"block_crop_ids": created},
        )
        assert undo.status_code == 200, undo.text
        assert undo.json()["assignment_count"] == 2

        b1 = (await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json()
        assert [r["season_label"] for r in b1] == ["2024A"]
        # ...and it is CURRENT again. `conflict_mode: replace` auto-closed it at
        # the new assignment's start; undoing the run has to rewind that too,
        # or the block silently ends up with no crop at all -- a worse state
        # than the mistake being undone.
        assert b1[0]["effective_to"] is None
        assert b1[0]["is_active_now"] is True
        assert undo.json()["reopened_count"] == 1
        # B2 had nothing before the run, so it goes back to empty.
        assert (await c.get(f"/api/v1/blocks/{blocks['B2']}/crop-assignments")).json() == []


@pytest.mark.asyncio
async def test_ids_from_another_farm_are_never_removed(admin_session: AsyncSession) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "rm-crossfarm")
    crop = await _crop_id(admin_session)
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_a, blocks_a = await _farm_with_blocks(c, ["A1"])
        bc_a = await _assign(c, blocks_a["A1"], crop, "2026A", "2026-01-01")

        farm_b = await c.post(
            "/api/v1/farms",
            json={"code": "RM2", "name": "Other", "boundary": _multipolygon(32.5, 29.0)},
        )
        farm_b_id = farm_b.json()["id"]

        # Farm B's endpoint, farm A's assignment id.
        resp = await c.post(
            f"/api/v1/farms/{farm_b_id}/bulk/crop-assignment:remove",
            json={"block_crop_ids": [bc_a]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["assignment_count"] == 0
        # Untouched.
        assert len((await c.get(f"/api/v1/blocks/{blocks_a['A1']}/crop-assignments")).json()) == 1


@pytest.mark.asyncio
async def test_selector_validation(admin_session: AsyncSession) -> None:
    tenant, user_id = await _seed_tenant(admin_session, "rm-validate")
    app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        url = f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove-preview"
        # Neither selector, both selectors, empty selector, duplicate ids.
        assert (await c.post(url, json={})).status_code == 422
        assert (
            await c.post(url, json={"block_ids": [blocks["B1"]], "block_crop_ids": [str(uuid4())]})
        ).status_code == 422
        assert (await c.post(url, json={"block_ids": []})).status_code == 422
        assert (
            await c.post(url, json={"block_ids": [blocks["B1"], blocks["B1"]]})
        ).status_code == 422


@pytest.mark.asyncio
async def test_removal_needs_the_delete_capability(admin_session: AsyncSession) -> None:
    """`crop_assignment.create` is not enough — an Agronomist can assign a crop
    but must not be able to erase the block's history."""
    tenant, user_id = await _seed_tenant(admin_session, "rm-rbac")
    crop = await _crop_id(admin_session)
    admin_app = build_app(
        make_context(
            user_id=user_id, tenant_id=tenant.tenant_id, tenant_role=TenantRole.TENANT_ADMIN
        )
    )
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        farm_id, blocks = await _farm_with_blocks(c, ["B1"])
        await _assign(c, blocks["B1"], crop, "2026A", "2026-01-01")

    for role in (FarmRole.AGRONOMIST, FarmRole.VIEWER):
        scoped = build_app(
            make_context(
                user_id=user_id,
                tenant_id=tenant.tenant_id,
                farm_scopes=(FarmScope(farm_id=UUID(farm_id), role=role),),
            )
        )
        async with AsyncClient(transport=ASGITransport(app=scoped), base_url="http://test") as c:
            resp = await c.post(
                f"/api/v1/farms/{farm_id}/bulk/crop-assignment:remove",
                json={"block_ids": [blocks["B1"]]},
            )
            assert resp.status_code in (403, 404), f"{role}: {resp.status_code}"

    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as c:
        assert len((await c.get(f"/api/v1/blocks/{blocks['B1']}/crop-assignments")).json()) == 1
