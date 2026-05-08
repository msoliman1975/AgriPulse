"""End-to-end check of the webhook delivery channel.

Spins up an in-process HTTP capture server on a random port, registers
its URL on the tenant's ``tenant_settings.webhook_endpoint_url``,
fires an alert, and asserts:

  * The receiver got a POST with the expected JSON shape.
  * The ``X-MissionAgre-Signature`` header matches an HMAC computed
    locally with the dev secret.
  * The dispatch row records ``status='sent'``.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import socket
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
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


class _CaptureHandler(BaseHTTPRequestHandler):
    captured: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        self.__class__.captured.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:
        # Silence stdlib's default per-request stderr line.
        pass


def _start_capture_server() -> tuple[HTTPServer, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = HTTPServer(("127.0.0.1", port), _CaptureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


@pytest.mark.asyncio
async def test_webhook_post_carries_valid_hmac_signature(
    admin_session: AsyncSession,
) -> None:
    register_subscribers(get_default_bus())
    _CaptureHandler.captured.clear()

    server, port = _start_capture_server()
    try:
        tenancy = get_tenant_service(admin_session)
        tenant = await tenancy.create_tenant(
            slug="pr-s4e-webhook",
            name="PR-S4-E webhook",
            contact_email="ops@pr-s4e.test",
        )
        # Register the capture URL on this tenant's settings. Fresh
        # tenants get a row inserted by tenancy bootstrap; UPDATE here.
        url = f"http://127.0.0.1:{port}/hooks/alerts"
        kms_key = "kms://test/key-1"
        await admin_session.execute(
            text(
                "UPDATE public.tenant_settings "
                "SET webhook_endpoint_url = :url, "
                "    webhook_signing_secret_kms_key = :kms, "
                "    alert_notification_channels = ARRAY['in_app','email','webhook']::text[] "
                "WHERE tenant_id = :tid"
            ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
            {"url": url, "kms": kms_key, "tid": tenant.tenant_id},
        )
        await admin_session.commit()

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

        # Wait briefly for the (sync, in-process) handler to land — the
        # handler runs inline in publish but tests sometimes race the
        # capture-server's accept loop.
        for _ in range(20):
            if _CaptureHandler.captured:
                break
            await asyncio.sleep(0.05)
        assert _CaptureHandler.captured, "capture server received no POST"

        captured = _CaptureHandler.captured[0]
        assert captured["path"] == "/hooks/alerts"
        # Verify signature with the same derivation the sender uses.
        expected_secret = f"{get_settings().webhook_dev_secret}::{kms_key}"
        digest = hmac.new(
            expected_secret.encode("utf-8"),
            captured["body"],
            hashlib.sha256,
        ).hexdigest()
        assert captured["headers"]["X-MissionAgre-Signature"] == f"sha256={digest}"
        assert captured["headers"]["X-MissionAgre-Event"] == "alert.opened"
        assert "X-MissionAgre-Delivery" in captured["headers"]

        body = json.loads(captured["body"])
        assert body["event"] == "alert.opened"
        assert body["rule_code"] == "ndvi_severe_drop"
        assert body["severity"] == "critical"
        assert body["block_id"] == str(block_id)

        # Dispatch row records the success.
        row = (
            (
                await admin_session.execute(
                    text(
                        f'SELECT status, recipient_address FROM "{tenant.schema_name}"'
                        f".notification_dispatches WHERE channel = 'webhook'"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row["status"] == "sent"
        assert row["recipient_address"] == url
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_webhook_skipped_when_url_unset(admin_session: AsyncSession) -> None:
    """A tenant with the webhook channel enabled but no URL gets a
    ``skipped`` dispatch with a clear reason."""
    register_subscribers(get_default_bus())

    tenancy = get_tenant_service(admin_session)
    tenant = await tenancy.create_tenant(
        slug="pr-s4e-no-url",
        name="PR-S4-E no URL",
        contact_email="ops@pr-s4e-nourl.test",
    )
    await admin_session.execute(
        text(
            "UPDATE public.tenant_settings "
            "SET alert_notification_channels = ARRAY['in_app','webhook']::text[] "
            "WHERE tenant_id = :tid"
        ).bindparams(bindparam("tid", type_=PG_UUID(as_uuid=True))),
        {"tid": tenant.tenant_id},
    )
    await admin_session.commit()

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

    row = (
        (
            await admin_session.execute(
                text(
                    f'SELECT status, error FROM "{tenant.schema_name}"'
                    f".notification_dispatches WHERE channel = 'webhook'"
                )
            )
        )
        .mappings()
        .one()
    )
    assert row["status"] == "skipped"
    assert "no webhook_endpoint_url" in (row["error"] or "")
