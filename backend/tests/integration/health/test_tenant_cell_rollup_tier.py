"""The tenant's rollup settings reach the health definition, through SQL.

`load_health_definitions` finds the tenant through the session's own
`app.current_tenant_id`, not through an argument. A unit test with a mocked
session cannot see whether that lookup matches anything, so this one runs
the statement against a real tenant session:

  * a tenant with no override reads the platform default, source "platform";
  * a tenant that chose `share` at 35% reads that, source "tenant";
  * another tenant's choice never leaks in.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.health.service import load_health_definitions
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal, sanitize_tenant_schema
from app.shared.keycloak import FakeKeycloakClient
from app.shared.settings import SettingsRepository

pytestmark = [pytest.mark.integration]


async def _tenant(admin_session: AsyncSession) -> Any:
    service = get_tenant_service(admin_session, keycloak_client=FakeKeycloakClient())
    tenant = await service.create_tenant(
        slug=f"rollup-{uuid4().hex[:8]}",
        name="Rollup",
        contact_email="ops@rollup.test",
        actor_user_id=None,
    )
    await admin_session.commit()
    return tenant


async def _override(admin_session: AsyncSession, tenant_id: Any, key: str, value: Any) -> None:
    await SettingsRepository(public_session=admin_session).upsert_tenant_override(
        tenant_id=tenant_id, key=key, value_json=json.dumps(value), actor_user_id=None
    )
    await admin_session.commit()


async def _resolve(schema: str) -> Any:
    """One tenant session, set up the way every request's is."""
    safe = sanitize_tenant_schema(schema)
    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f"SET LOCAL search_path TO {safe}, public"))
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :v, TRUE)"), {"v": safe}
        )
        definitions = await load_health_definitions(session, farm_id=uuid4())
        return definitions.for_path(None)


@pytest.mark.asyncio
async def test_no_override_reads_the_platform_default(admin_session: AsyncSession) -> None:
    tenant = await _tenant(admin_session)
    resolved = await _resolve(tenant.schema_name)
    assert resolved.source == "platform"
    assert resolved.definition.cell_rollup == "worst"


@pytest.mark.asyncio
async def test_the_tenant_choice_is_read_and_named(admin_session: AsyncSession) -> None:
    chooser = await _tenant(admin_session)
    other = await _tenant(admin_session)
    await _override(admin_session, chooser.tenant_id, "health.cell_rollup", "share")
    await _override(admin_session, chooser.tenant_id, "health.cell_share_pct", 35)

    resolved = await _resolve(chooser.schema_name)
    assert resolved.source == "tenant"
    assert resolved.definition.cell_rollup == "share"
    assert resolved.definition.cell_critical_share == Decimal("0.35")

    # The other tenant made no choice and must not read this one's.
    assert (await _resolve(other.schema_name)).source == "platform"
