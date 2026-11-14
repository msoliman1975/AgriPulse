"""End-to-end check of the realtime pub/sub helper.

Publish from a sync caller (mirrors the notifications subscriber) and
read from the async generator (mirrors the SSE endpoint). Uses the
live dev Redis from the compose stack — same instance the rest of
the integration suite assumes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest

from app.shared.realtime import _channel, _get_sync_client, publish_to_user, subscribe

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

    # `subscribe()` sends SUBSCRIBE and yields the primer without waiting for
    # Redis to confirm it, so in principle a publish straight after can land
    # before the subscription exists and be dropped. That is fine for the
    # product (the push is best-effort and the inbox reloads on reconnect) but
    # would make this test a race, so wait until Redis counts the subscriber.
    #
    # This test timed out once, in one of seven local 3-worker runs, before
    # this wait existed; it has not been reproduced since. In every probed run
    # (three full parallel runs, 300 solo runs under CPU load) Redis had the
    # subscription registered within ~15 ms and delivered in ~2 ms, so this
    # race is the one plausible cause found, not a proven one. If it times out
    # again, the failure message below says which side lost the message.
    channel = _channel(tenant_id, user_id)
    for _ in range(100):
        counts: Any = _get_sync_client().pubsub_numsub(channel)  # sync client: a list
        numsub = dict(counts)
        if numsub.get(channel, 0) >= 1:
            break
        await asyncio.sleep(0.03)
    else:
        pytest.fail("Redis never registered the subscription")

    payload = {"id": "abc", "title": "hello"}
    publish_to_user(tenant_id=tenant_id, user_id=user_id, payload=payload)

    # Pull frames until the inbox event arrives, skipping any keepalives.
    seen: list[str] = []

    async def _next_inbox_event_recording() -> str:
        while True:
            frame = await gen.__anext__()
            seen.append(frame.split("\n", 1)[0])
            if frame.startswith("event: inbox"):
                return frame

    # `asyncio.wait`, not `wait_for`: on timeout it leaves the reader running,
    # so the subscriber count below is taken while the subscription is still
    # open. `wait_for` would cancel into the generator, whose `finally`
    # unsubscribes, and the count would always read 0.
    reader = asyncio.ensure_future(_next_inbox_event_recording())
    done, _ = await asyncio.wait({reader}, timeout=3.0)
    if not done:
        counts_after: Any = _get_sync_client().pubsub_numsub(channel)
        reader.cancel()
        pytest.fail(
            "inbox event never arrived within 3 s. Redis subscribers on the channel "
            f"at the deadline: {dict(counts_after).get(channel, 0)}; frames seen: "
            f"{seen}. Subscribers >= 1 means the subscription was live and the read "
            "side lost the message; 0 means the subscriber connection had dropped."
        )
    frame = reader.result()
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
