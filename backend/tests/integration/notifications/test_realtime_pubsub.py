"""End-to-end check of the realtime pub/sub helper.

Publish from a sync caller (mirrors the notifications subscriber) and
read from the async generator (mirrors the SSE endpoint). Uses the
live dev Redis from the compose stack — same instance the rest of
the integration suite assumes.
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from app.shared.realtime import publish_to_user, subscribe

pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_publish_to_user_reaches_subscribe_within_a_second() -> None:
    tenant_id = uuid4()
    user_id = uuid4()

    gen = subscribe(tenant_id=tenant_id, user_id=user_id, keepalive_seconds=2.0)
    # Drain the initial ": connected\n\n" comment so we know the
    # subscription is active before we publish.
    primer = await asyncio.wait_for(gen.__anext__(), timeout=3.0)
    assert primer.startswith(": connected")

    payload = {"id": "abc", "title": "hello"}
    publish_to_user(tenant_id=tenant_id, user_id=user_id, payload=payload)

    # Pull frames until the inbox event arrives, skipping any keepalives.
    async def _next_inbox_event() -> str:
        while True:
            frame = await gen.__anext__()
            if frame.startswith("event: inbox"):
                return frame

    frame = await asyncio.wait_for(_next_inbox_event(), timeout=3.0)
    # frame format: "event: inbox\ndata: <json>\n\n"
    data_line = next(line for line in frame.split("\n") if line.startswith("data: "))
    decoded = json.loads(data_line.removeprefix("data: "))
    assert decoded == payload

    await gen.aclose()


@pytest.mark.asyncio
async def test_subscribe_emits_keepalive_when_idle() -> None:
    tenant_id = uuid4()
    user_id = uuid4()

    gen = subscribe(tenant_id=tenant_id, user_id=user_id, keepalive_seconds=0.5)
    # Drain primer.
    await asyncio.wait_for(gen.__anext__(), timeout=2.0)

    # No publish — first follow-up frame should be a keepalive comment.
    frame = await asyncio.wait_for(gen.__anext__(), timeout=3.0)
    assert frame.startswith(": keepalive")

    await gen.aclose()
