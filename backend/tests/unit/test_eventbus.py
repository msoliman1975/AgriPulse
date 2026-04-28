"""Unit tests for the in-process event bus."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.shared.eventbus import Event, EventBus


class SampleCreatedV1(Event):
    event_name = "test.sample_created.v1"

    sample_id: UUID
    name: str


class OtherEventV1(Event):
    event_name = "test.other.v1"
    value: int


def test_sync_subscriber_runs_inline() -> None:
    bus = EventBus()
    seen: list[UUID] = []

    @bus.subscribe(SampleCreatedV1)
    def on(e: SampleCreatedV1) -> None:
        seen.append(e.sample_id)

    sid = uuid4()
    bus.publish(SampleCreatedV1(sample_id=sid, name="x"))
    assert seen == [sid]


def test_publish_with_no_subscribers_is_noop() -> None:
    bus = EventBus()
    bus.publish(OtherEventV1(value=5))


def test_sync_handler_exception_propagates() -> None:
    bus = EventBus()

    @bus.subscribe(SampleCreatedV1)
    def boom(e: SampleCreatedV1) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        bus.publish(SampleCreatedV1(sample_id=uuid4(), name="x"))


def test_async_subscriber_dispatches_via_dispatcher() -> None:
    bus = EventBus()
    calls: list[tuple[str, str, dict[str, object]]] = []

    def dispatcher(*, handler_name: str, event_name: str, payload: dict[str, object]) -> None:
        calls.append((handler_name, event_name, payload))

    bus.set_dispatcher(dispatcher)

    @bus.subscribe(SampleCreatedV1, mode="async")
    def on_async(e: SampleCreatedV1) -> None:
        pass

    sid = uuid4()
    bus.publish(SampleCreatedV1(sample_id=sid, name="x"))

    assert len(calls) == 1
    handler_name, event_name, payload = calls[0]
    assert event_name == "test.sample_created.v1"
    assert payload["sample_id"] == str(sid)
    assert payload["name"] == "x"


def test_async_without_dispatcher_warns_but_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus()

    @bus.subscribe(SampleCreatedV1, mode="async")
    def on_async(e: SampleCreatedV1) -> None:
        pass

    bus.publish(SampleCreatedV1(sample_id=uuid4(), name="x"))


def test_resolve_handler_and_event() -> None:
    bus = EventBus()

    @bus.subscribe(SampleCreatedV1)
    def on(e: SampleCreatedV1) -> None:
        pass

    handler = bus.resolve_handler(f"{on.__module__}:{on.__qualname__}")
    assert handler is on
    assert bus.resolve_event("test.sample_created.v1") is SampleCreatedV1


def test_resolve_handler_unknown_raises() -> None:
    bus = EventBus()
    with pytest.raises(LookupError):
        bus.resolve_handler("no.such:handler")


def test_register_rejects_async_coroutines() -> None:
    bus = EventBus()

    async def coro(e: SampleCreatedV1) -> None:
        pass

    with pytest.raises(TypeError, match="must be a sync function"):
        bus.register(SampleCreatedV1, coro, mode="async")


def test_clear_drops_registrations() -> None:
    bus = EventBus()

    @bus.subscribe(SampleCreatedV1)
    def on(e: SampleCreatedV1) -> None:
        pass

    assert tuple(bus.handlers_for(SampleCreatedV1))
    bus.clear()
    assert tuple(bus.handlers_for(SampleCreatedV1)) == ()
