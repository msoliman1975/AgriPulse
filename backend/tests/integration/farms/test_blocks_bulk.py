"""Integration tests for POST /farms/{farm_id}/blocks:bulk — the bulk
AOI-upload reconcile.

Covers the identity-by-code contract:

  * new code                       -> created
  * code + identical geometry      -> reused (no write)
  * code + changed geometry        -> replaced (delete if pristine, else
    inactivate), gated on allow_replace + delete capability
  * malformed rows                 -> per-row error, batch stays alive
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service
from app.shared.auth.context import TenantRole

from .conftest import build_app, make_context
from .test_farms_crud import _create_user_in_tenant, _square

pytestmark = [pytest.mark.integration]


def _polygon(lon: float, lat: float, side: float = 0.003) -> dict[str, object]:
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


async def _bootstrap_tenant(admin_session: AsyncSession, slug: str) -> tuple[object, object]:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name=f"Bulk {slug}",
        contact_email=f"ops@{slug}.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    context = make_context(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        tenant_role=TenantRole.TENANT_ADMIN,
    )
    return tenant, context


async def _create_farm(client: AsyncClient, *, code: str = "FARM-BULK") -> str:
    resp = await client.post(
        "/api/v1/farms",
        json={
            "code": code,
            "name": f"Bulk Farm {code}",
            "boundary": _square(31.20, 30.10),
            "farm_type": "commercial",
            "tags": [],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_bulk_create_new_blocks(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "bulk-new")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={
                "items": [
                    {"code": "N-1", "name": "North 1", "boundary": _polygon(31.21, 30.11)},
                    {"code": "N-2", "boundary": _polygon(31.22, 30.11)},
                ]
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 2
    assert body["reused"] == 0
    assert body["replaced"] == 0
    assert body["errors"] == 0
    assert [r["status"] for r in body["results"]] == ["created", "created"]
    assert all(r["block_id"] for r in body["results"])


@pytest.mark.asyncio
async def test_bulk_reuse_identical_geometry(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "bulk-reuse")
    app = build_app(context)
    geom = _polygon(31.21, 30.11)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        first = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={"items": [{"code": "R-1", "boundary": geom}]},
        )
        created_id = first.json()["results"][0]["block_id"]

        # Re-upload the exact same code + geometry.
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={"items": [{"code": "R-1", "boundary": geom}]},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reused"] == 1
    assert body["created"] == 0
    row = body["results"][0]
    assert row["status"] == "reused"
    # Reuse returns the SAME existing block, nothing new created.
    assert row["block_id"] == created_id


@pytest.mark.asyncio
async def test_bulk_replace_pristine_block_hard_deletes(admin_session: AsyncSession) -> None:
    tenant, context = await _bootstrap_tenant(admin_session, "bulk-replace-del")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        first = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={"items": [{"code": "D-1", "boundary": _polygon(31.21, 30.11)}]},
        )
        old_id = first.json()["results"][0]["block_id"]

        # Same code, different geometry, with confirmation.
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={
                "allow_replace": True,
                "items": [{"code": "D-1", "boundary": _polygon(31.25, 30.11)}],
            },
        )
    assert resp.status_code == 200, resp.text
    row = resp.json()["results"][0]
    assert row["status"] == "replaced_deleted"
    assert row["replaced_block_id"] == old_id
    assert row["block_id"] != old_id

    # Old pristine block was hard-deleted: no row remains.
    cnt = (
        await admin_session.execute(
            text(f'SELECT count(*) FROM "{tenant.schema_name}".blocks WHERE id = :id'),
            {"id": old_id},
        )
    ).scalar_one()
    assert cnt == 0


@pytest.mark.asyncio
async def test_bulk_replace_block_with_dependents_inactivates(admin_session: AsyncSession) -> None:
    tenant, context = await _bootstrap_tenant(admin_session, "bulk-replace-inact")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        first = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={"items": [{"code": "I-1", "boundary": _polygon(31.21, 30.11)}]},
        )
        old_id = first.json()["results"][0]["block_id"]

        # Make the block non-pristine by attaching a growth-stage log row.
        await admin_session.execute(
            text(
                f'INSERT INTO "{tenant.schema_name}".growth_stage_logs '
                "(id, block_id, stage) VALUES (gen_random_uuid(), :bid, 'flowering')"
            ),
            {"bid": old_id},
        )
        await admin_session.commit()

        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={
                "allow_replace": True,
                "items": [{"code": "I-1", "boundary": _polygon(31.25, 30.11)}],
            },
        )
    assert resp.status_code == 200, resp.text
    row = resp.json()["results"][0]
    assert row["status"] == "replaced_inactivated"
    assert row["replaced_block_id"] == old_id

    # Old block still exists but is soft-inactivated (deleted_at stamped).
    deleted_at = (
        await admin_session.execute(
            text(f'SELECT deleted_at FROM "{tenant.schema_name}".blocks WHERE id = :id'),
            {"id": old_id},
        )
    ).scalar_one()
    assert deleted_at is not None


@pytest.mark.asyncio
async def test_bulk_replace_requires_confirmation(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "bulk-noconfirm")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={"items": [{"code": "C-1", "boundary": _polygon(31.21, 30.11)}]},
        )
        # Changed geometry but allow_replace defaults to False.
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={"items": [{"code": "C-1", "boundary": _polygon(31.25, 30.11)}]},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["errors"] == 1
    assert body["replaced"] == 0
    row = body["results"][0]
    assert row["status"] == "error"
    assert row["error_code"] == "replace_not_confirmed"


@pytest.mark.asyncio
async def test_bulk_error_rows_do_not_fail_batch(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "bulk-errors")
    app = build_app(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        farm_id = await _create_farm(client)
        resp = await client.post(
            f"/api/v1/farms/{farm_id}/blocks:bulk",
            json={
                "items": [
                    {"code": "OK-1", "boundary": _polygon(31.21, 30.11)},
                    {"code": "bad code!", "boundary": _polygon(31.22, 30.11)},
                    {"code": "DUP", "boundary": _polygon(31.23, 30.11)},
                    {"code": "DUP", "boundary": _polygon(31.24, 30.11)},
                    {"code": "OUT", "boundary": _polygon(10.0, 10.0)},
                ]
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    statuses = [(r["status"], r.get("error_code")) for r in body["results"]]
    assert statuses[0] == ("created", None)
    assert statuses[1] == ("error", "invalid_code")
    assert statuses[2] == ("created", None)  # first DUP wins
    assert statuses[3] == ("error", "duplicate_in_batch")
    assert statuses[4] == ("error", "out_of_egypt")
    assert body["created"] == 2
    assert body["errors"] == 3
