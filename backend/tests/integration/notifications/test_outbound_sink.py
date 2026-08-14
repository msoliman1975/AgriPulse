"""End-to-end proof that the notification sink is actually wired in.

The unit tests cover the sink's logic. What they cannot cover is the risky
part: whether each subscriber really *activates* the context before it fans
out. A sink that resolves correctly but is never switched on looks fine in
isolation and mails real customers in production.

The in-app assertions matter as much as the suppression ones. Suppression is
about traffic that leaves the system; the inbox is internal, and a sink that
silenced it would make a simulation run untestable through the UI the personas
actually read.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.notifications.sink import SUPPRESSED_REASON
from app.modules.notifications.subscribers import register_subscribers
from app.modules.recommendations.loader import sync_from_disk
from app.modules.tenancy.service import get_tenant_service
from app.shared.eventbus import get_default_bus
from tests.integration.farms.test_farms_crud import _create_user_in_tenant
from tests.integration.notifications.test_inbox_dispatch_on_alert_opened import (
    _attach_user_to_farm,
    _evaluate_via_tree,
    _seed_block_with_ndvi_row,
)

pytestmark = [pytest.mark.integration]


@pytest.fixture
def _sink_prefix(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("NOTIFICATION_SINK_TENANT_PREFIX", "simsink-")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("NOTIFICATION_SINK_TENANT_PREFIX", raising=False)
    get_settings.cache_clear()


async def _fire_alert_for(admin_session: AsyncSession, *, slug: str) -> tuple[Any, Any]:
    """Provision a tenant, wire a recipient, and drive one alert through."""
    register_subscribers(get_default_bus())
    await sync_from_disk(admin_session)

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug=slug,
        name="Sink test",
        contact_email="ops@sink.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )
    await _attach_user_to_farm(
        admin_session, tenant_id=tenant.tenant_id, user_id=user_id, farm_id=farm_id
    )
    await _evaluate_via_tree(tenant.schema_name, tenant.tenant_id, block_id)
    return tenant, user_id


async def _dispatches(
    admin_session: AsyncSession, *, schema: str, user_id: Any
) -> list[dict[str, Any]]:
    rows = (
        await admin_session.execute(
            text(
                f'SELECT channel, status, error FROM "{schema}".notification_dispatches '
                f"WHERE recipient_user_id = :uid OR recipient_user_id IS NULL"
            ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
            {"uid": user_id},
        )
    ).mappings()
    return [dict(r) for r in rows]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_sink_prefix")
async def test_matching_tenant_suppresses_email_but_keeps_the_inbox(
    admin_session: AsyncSession,
) -> None:
    tenant, user_id = await _fire_alert_for(admin_session, slug=f"simsink-{uuid4().hex[:6]}")
    rows = await _dispatches(admin_session, schema=tenant.schema_name, user_id=user_id)

    email = [r for r in rows if r["channel"] == "email"]
    assert email, "no email dispatch row was written at all"
    assert all(r["status"] == "skipped" for r in email), email
    assert all(r["error"] == SUPPRESSED_REASON for r in email), email
    # Nothing may claim to have been delivered.
    assert not [r for r in email if r["status"] == "sent"]

    # In-app is internal and must survive: it is the surface the personas read.
    in_app = [r for r in rows if r["channel"] == "in_app"]
    assert "sent" in {r["status"] for r in in_app}, in_app


@pytest.mark.asyncio
async def test_non_matching_tenant_still_delivers(admin_session: AsyncSession) -> None:
    """The regression that would silence a real customer.

    Runs with no prefix configured — the production default — so email must
    reach the transport exactly as before.
    """
    tenant, user_id = await _fire_alert_for(admin_session, slug=f"realish-{uuid4().hex[:6]}")
    rows = await _dispatches(admin_session, schema=tenant.schema_name, user_id=user_id)

    email = [r for r in rows if r["channel"] == "email"]
    assert email
    assert "sent" in {r["status"] for r in email}, email
    assert SUPPRESSED_REASON not in {r["error"] for r in email}
