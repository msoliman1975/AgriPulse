"""DB-backed regression test for the weather-summary crop-context query.

The crop_path filter is applied in SQL (unlike crop-health, which filters in
Python), so it must run against the real asyncpg driver. A previous version
bound `:crop_path` untyped and asyncpg raised
``AmbiguousParameterError: could not determine data type of parameter`` on
*every* call (filter or not) — casting the bind to text fixes it. The unit
tests mock this helper, so only a real DB session catches the driver issue.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.modules.reports.service import _select_weather_crop_context
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.ids import schema_name_for

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
@pytest.mark.parametrize("crop_path", [None, "mango", "mango.alphonso.short"])
async def test_weather_crop_context_runs_against_asyncpg(
    admin_session: object, crop_path: str | None
) -> None:
    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=f"wx-ctx-{uuid4().hex[:8]}",
        name="Weather Ctx",
        contact_email="ops@wx-ctx.test",
    )
    schema = schema_name_for(tenant.tenant_id)

    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session:
        await session.execute(text(f'SET search_path TO "{schema}", public'))
        # No blocks/crops seeded → empty result, but the query must execute
        # without AmbiguousParameterError for both the null (no-filter) and
        # the prefix-filter binds.
        rows = await _select_weather_crop_context(session, farm_id=uuid4(), crop_path=crop_path)
        assert rows == []
