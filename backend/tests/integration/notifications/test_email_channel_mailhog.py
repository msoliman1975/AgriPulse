"""Verify the email channel actually delivers through MailHog.

Requires the dev compose stack's `mailhog` service running on
localhost:1025/8025. The test:

  1. Clears MailHog's inbox via its HTTP API.
  2. Fires an alert through the engine, which triggers the
     notifications subscriber → SMTP send.
  3. Polls MailHog's inbox until the message arrives, then asserts the
     subject/recipient match the rendered template.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.service import get_alerts_service
from app.modules.notifications.subscribers import register_subscribers
from app.modules.tenancy.service import get_tenant_service
from app.shared.db.session import AsyncSessionLocal
from app.shared.eventbus import get_default_bus
from tests.integration.alerts.test_alerts_pipeline import _seed_block_with_ndvi_row
from tests.integration.farms.test_farms_crud import _create_user_in_tenant
from tests.integration.notifications.test_inbox_dispatch_on_alert_opened import (
    _attach_user_to_farm,
)

pytestmark = [pytest.mark.integration]

_MAILHOG_API = "http://localhost:8025"


async def _mailhog_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{_MAILHOG_API}/api/v2/messages")
            return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


async def _clear_mailhog() -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.delete(f"{_MAILHOG_API}/api/v1/messages")


async def _wait_for_message_to(address: str, timeout_s: float = 5.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with httpx.AsyncClient(timeout=2.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            resp = await client.get(f"{_MAILHOG_API}/api/v2/messages")
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("items", []):
                tos = [t.get("Mailbox", "") + "@" + t.get("Domain", "") for t in item.get("To", [])]
                if address in tos:
                    return item
            await asyncio.sleep(0.2)
    raise AssertionError(f"no MailHog message for {address} within {timeout_s}s")


@pytest.mark.asyncio
async def test_alert_email_arrives_in_mailhog(admin_session: AsyncSession) -> None:
    if not await _mailhog_available():
        pytest.skip("MailHog not running on localhost:8025 — start it via compose")

    register_subscribers(get_default_bus())
    await _clear_mailhog()

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4d-mailhog",
        name="PR-S4-D MailHog",
        contact_email="ops@pr-s4d.test",
    )
    user_id = uuid4()
    await _create_user_in_tenant(admin_session, tenant_id=tenant.tenant_id, user_id=user_id)
    farm_id, block_id = await _seed_block_with_ndvi_row(
        admin_session, tenant.schema_name, deviation=Decimal("-2.0")
    )
    await _attach_user_to_farm(
        admin_session, tenant_id=tenant.tenant_id, user_id=user_id, farm_id=farm_id
    )

    factory = AsyncSessionLocal()
    async with factory() as session, session.begin():
        await session.execute(text(f'SET LOCAL search_path TO "{tenant.schema_name}", public'))
        async with factory() as public_session:
            svc = get_alerts_service(tenant_session=session, public_session=public_session)
            await svc.evaluate_block(
                block_id=block_id,
                actor_user_id=None,
                tenant_schema=tenant.schema_name,
            )

    expected_address = f"u-{user_id}@example.test"
    message = await _wait_for_message_to(expected_address)
    subject_header = next(
        (v[0] for k, v in message["Content"]["Headers"].items() if k.lower() == "subject"),
        "",
    )
    assert "Agri.Pulse" in subject_header
    assert "alert" in subject_header.lower() or "تنبيه" in subject_header

    # And the dispatch row reflects status='sent'.
    row = (
        (
            await admin_session.execute(
                text(
                    f"SELECT status, recipient_address FROM "
                    f'"{tenant.schema_name}".notification_dispatches '
                    "WHERE channel = 'email' AND recipient_user_id = :uid"
                ).bindparams(bindparam("uid", type_=PG_UUID(as_uuid=True))),
                {"uid": user_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["status"] == "sent"
    assert row["recipient_address"] == expected_address


_ = UUID  # keep import for future strict typing
