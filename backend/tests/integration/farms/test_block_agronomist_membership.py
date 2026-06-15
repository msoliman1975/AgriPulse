"""U-4b: blocks carry agronomist_membership_id (repointed from agronomist_id).

The per-block agronomist now references a tenant membership instead of a raw
users.id (tenant migration 0046). Like the U-3 worker link it's a logical
cross-schema reference with no FK, so any membership UUID round-trips at this
layer — we assert the plumbing (create / read / update / unlink), not
referential integrity.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import build_app
from .test_blocks_unit_type import _bootstrap_tenant, _polygon
from .test_farms_crud import _square

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_block_agronomist_membership_round_trip(admin_session: AsyncSession) -> None:
    _tenant, context = await _bootstrap_tenant(admin_session, "blk-agro-mem")
    app = build_app(context)
    membership_id = str(uuid4())
    other_membership_id = str(uuid4())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        farm = await c.post(
            "/api/v1/farms",
            json={
                "code": "AGRO-FARM",
                "name": "Agro Farm",
                "boundary": _square(31.50, 30.50),
                "farm_type": "commercial",
            },
        )
        assert farm.status_code == 201, farm.text
        farm_id = farm.json()["id"]

        created = await c.post(
            f"/api/v1/farms/{farm_id}/blocks",
            json={
                "code": "AGRO-B1",
                "boundary": _polygon(31.51, 30.51),
                "agronomist_membership_id": membership_id,
            },
        )
        assert created.status_code == 201, created.text
        block_id = created.json()["id"]
        assert created.json()["agronomist_membership_id"] == membership_id

        # Read back.
        got = await c.get(f"/api/v1/blocks/{block_id}")
        assert got.status_code == 200, got.text
        assert got.json()["agronomist_membership_id"] == membership_id

        # Reassign to another member.
        patched = await c.patch(
            f"/api/v1/blocks/{block_id}",
            json={"agronomist_membership_id": other_membership_id},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["agronomist_membership_id"] == other_membership_id
