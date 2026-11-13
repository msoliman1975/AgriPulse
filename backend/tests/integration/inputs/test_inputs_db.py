"""D20 on Postgres: the platform seed, tenant isolation and crop scope."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.inputs.repository import InputsRepository
from app.modules.tenancy import get_tenant_service


async def _tenant(admin_session: Any) -> Any:
    slug = f"inputs-{uuid4().hex[:8]}"
    tenant = await get_tenant_service(admin_session).create_tenant(
        slug=slug, name=slug, contact_email=f"o@{slug}.test"
    )
    await admin_session.commit()
    return tenant.tenant_id


@pytest.mark.asyncio
async def test_platform_seed_and_tenant_rows_stay_apart(admin_session: Any) -> None:
    repo = InputsRepository(admin_session)
    sulphur = await repo.list_inputs(
        tenant_id=None,
        crop_path="date_palm.medjool",
        category="mineral_or_botanical_treatment",
        q="sulphur",
        include_inactive=False,
    )
    seeded = next(i for i in sulphur if i["code"] == "sulphur")
    assert seeded["organic_status"] == "unverified"
    assert seeded["doses"]

    mine, theirs = await _tenant(admin_session), await _tenant(admin_session)
    own = await repo.create(
        mine,
        {
            "code": "sulphur",
            "name_en": "Our sulphur",
            "category": "mineral_or_botanical_treatment",
            "crop_paths": ["mango"],
        },
        None,
    )
    assert await repo.code_taken("sulphur", mine)
    assert not await repo.code_taken("sulphur", theirs)

    seen = await repo.list_inputs(
        tenant_id=mine, crop_path="mango.keitt", category=None, q="sulphur", include_inactive=False
    )
    assert {(i["code"], i["scope"]) for i in seen} >= {
        ("sulphur", "tenant"),
        ("sulphur", "platform"),
    }
    other = await repo.list_inputs(
        tenant_id=theirs, crop_path=None, category=None, q="Our sulphur", include_inactive=False
    )
    assert other == []
    # Scoped to mango: not offered on date palm.
    palm = await repo.list_inputs(
        tenant_id=mine,
        crop_path="date_palm",
        category=None,
        q="Our sulphur",
        include_inactive=False,
    )
    assert palm == []
    await repo.update(own, {"is_active": False}, None)
