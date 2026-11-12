"""DB-backed smoke test for the D21/D6 signals SQL.

The unit tests check the rules in Python; only a real asyncpg session catches
a statement that fails to plan (an ambiguous untyped bind, a bad unnest alias,
a missing column after migration 0102). The tenant is empty on purpose: what
is under test is that each statement executes.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.signals.repository import SignalsRepository
from app.modules.signals.snapshot import load_snapshot
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.ids import schema_name_for

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_crop_scoped_signal_sql_runs_against_asyncpg(admin_session: object) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"sig-crop-{uuid4().hex[:8]}",
        name="Crop-scoped signals",
        contact_email="ops@sig-crop.test",
    )
    schema = schema_name_for(tenant.tenant_id)

    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session:
        await session.execute(text(f'SET search_path TO "{schema}", public'))

        assert await load_snapshot(session, block_id=uuid4(), farm_id=uuid4()) == {}

        repo = SignalsRepository(session)
        everything = await repo.list_definitions(include_inactive=True)
        for_medjool = await repo.list_definitions(
            include_inactive=True, crop_path="date_palm.medjool"
        )
        # The filter only ever narrows, and every row carries a scope list.
        assert {d["code"] for d in for_medjool} <= {d["code"] for d in everything}
        assert all(isinstance(d["crop_paths"], list) for d in everything)
        await repo.list_templates(include_inactive=True, crop_path="mango")
