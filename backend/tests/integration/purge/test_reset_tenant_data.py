"""``tenant_data`` — wipe a tenant's farms and blocks, keep the tenant itself.

This is the primitive the testing-phase workflow actually needs: a clean slate
without re-running provisioning, re-inviting users, or re-entering integration
keys. Its archive-first analogue is at the tenant level — the tenant has to be
suspended (or pending-delete) before its data can be wiped.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.service import get_tenant_service

from .conftest import client_for, polygon, square

pytestmark = [pytest.mark.integration]


async def _seed_two_farms(client: Any) -> None:
    for i, code in enumerate(("A", "B")):
        farm = await client.post(
            "/api/v1/farms",
            json={"code": code, "name": code, "boundary": square(31.2 + i * 0.05, 30.0)},
        )
        assert farm.status_code == 201, farm.text
        block = await client.post(
            f"/api/v1/farms/{farm.json()['id']}/blocks",
            json={"code": f"{code}-1", "boundary": polygon(31.201 + i * 0.05, 30.001)},
        )
        assert block.status_code == 201, block.text


@pytest.mark.asyncio
async def test_active_tenant_is_refused(tenant_env: dict[str, Any]) -> None:
    async with client_for(tenant_env["tenant_context"]) as tc:
        await _seed_two_farms(tc)

    async with client_for(tenant_env["platform_context"]) as pc:
        preview = (
            await pc.get(
                "/api/v1/admin/purge/preview",
                params={
                    "kind": "tenant_data",
                    "id": str(tenant_env["tenant_id"]),
                    "tenant_id": str(tenant_env["tenant_id"]),
                },
            )
        ).json()
        assert preview["archived"] is False
        assert preview["blocking"][0]["reason"] == "tenant_not_suspended"

        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "tenant_data",
                "id": str(tenant_env["tenant_id"]),
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": tenant_env["slug"],
            },
        )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_reset_wipes_farms_but_keeps_the_tenant(
    tenant_env: dict[str, Any], admin_session: AsyncSession
) -> None:
    schema = tenant_env["schema_name"]
    async with client_for(tenant_env["tenant_context"]) as tc:
        await _seed_two_farms(tc)

    await get_tenant_service(admin_session).suspend_tenant(
        tenant_env["tenant_id"], reason="test reset"
    )
    await admin_session.commit()

    async with client_for(tenant_env["platform_context"]) as pc:
        resp = await pc.post(
            "/api/v1/admin/purge",
            json={
                "kind": "tenant_data",
                "id": str(tenant_env["tenant_id"]),
                "tenant_id": str(tenant_env["tenant_id"]),
                "confirmation": tenant_env["slug"],
                "reason": "clean slate for the next test run",
            },
        )
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "succeeded", job
    assert job["receipt"]["verification"]["orphans_found"] == 0
    assert job["receipt"]["deleted"]["db_rows"]["farms"] == 2
    assert job["receipt"]["deleted"]["db_rows"]["blocks"] == 2

    await admin_session.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    farms = (await admin_session.execute(text("SELECT count(*) FROM farms"))).scalar_one()
    blocks = (await admin_session.execute(text("SELECT count(*) FROM blocks"))).scalar_one()
    await admin_session.rollback()
    assert farms == 0
    assert blocks == 0

    # The tenant, its schema and its membership all survive — that is the whole
    # point of this kind versus a full tenant purge.
    tenant_row = (
        await admin_session.execute(
            text("SELECT status FROM public.tenants WHERE id = :t").bindparams(
                bindparam("t", type_=PG_UUID(as_uuid=True))
            ),
            {"t": tenant_env["tenant_id"]},
        )
    ).scalar_one_or_none()
    assert tenant_row == "suspended"

    members = (
        await admin_session.execute(
            text("SELECT count(*) FROM public.tenant_memberships WHERE tenant_id = :t").bindparams(
                bindparam("t", type_=PG_UUID(as_uuid=True))
            ),
            {"t": tenant_env["tenant_id"]},
        )
    ).scalar_one()
    assert members == 1
