"""In-process event bus for cross-module reactions.

Cross-module *commands* (give me X, do Y) go through service Protocols
imported via dependency injection. Cross-module *reactions* (X happened,
Y wants to know) go through this bus, per ARCHITECTURE.md § 6.2.

Two subscriber modes:

  - ``sync``  : handler runs inline in the publisher's thread/transaction.
                Failures bubble. Use when the reaction must complete
                before the request returns (e.g., audit write).
  - ``async`` : handler is dispatched as a Celery task. Failures surface
                in the worker, not the publisher. Use for fan-out, slow
                work, or anything that must not block the request.

Subscribers register at app startup, either via the ``@bus.subscribe(...)``
decorator on a module-level function, or via the explicit
``bus.register(event_cls, handler, mode=...)`` call.

The Celery integration is injected: the bus calls a ``CeleryDispatcher``
callable (set once during app/celery factory setup). This keeps
``app.shared.eventbus`` free of any Celery import so it can be used in
the API process without spinning up a worker.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict

from app.core.logging import get_logger

EventT = TypeVar("EventT", bound="Event")
SubscriberMode = Literal["sync", "async"]


class Event(BaseModel):
    """Base class for module events.

    Subclasses set ``event_name`` (a stable string used for routing
    through Celery and for log/trace correlation) and define their
    payload as Pydantic fields. Versioning is by name suffix; the class
    name should mirror the event_name (``FarmCreatedV1`` →
    ``"farms.farm_created.v1"``).
    """

    model_config = ConfigDict(frozen=True)
    event_name: ClassVar[str]


class CeleryDispatcher(Protocol):
    """Bridge so the bus does not import Celery directly.

    Implementations enqueue a task that, in the worker, looks up the
    handler by ``handler_name`` and runs it on the deserialized payload.
    """

    def __call__(self, *, handler_name: str, event_name: str, payload: dict[str, Any]) -> None: ...


HandlerCallable = Callable[[Any], None]


@dataclass(slots=True, frozen=True)
class Subscription:
    """One registered handler. Returned from `handlers_for`."""

    handler: HandlerCallable
    mode: SubscriberMode


class EventBus:
    """In-process event bus.

    A single shared instance lives at ``get_default_bus()`` and is what
    application code should use; tests construct their own.
    """

    def __init__(self, dispatcher: CeleryDispatcher | None = None) -> None:
        self._handlers: dict[type[Event], list[Subscription]] = {}
        self._handlers_by_name: dict[str, HandlerCallable] = {}
        self._events_by_name: dict[str, type[Event]] = {}
        self._dispatcher = dispatcher
        self._log = get_logger(__name__)

    # -- wiring -----------------------------------------------------------

    def set_dispatcher(self, dispatcher: CeleryDispatcher | None) -> None:
        """Wire (or unwire) the Celery bridge. Called once at startup."""
        self._dispatcher = dispatcher

    # -- registration -----------------------------------------------------

    def subscribe(
        self, event_cls: type[EventT], *, mode: SubscriberMode = "sync"
    ) -> Callable[[Callable[[EventT], None]], Callable[[EventT], None]]:
        """Decorator form. Use on module-level functions only.

        ``@bus.subscribe(FarmCreatedV1, mode="async")``
        """

        def _wrap(handler: Callable[[EventT], None]) -> Callable[[EventT], None]:
            self.register(event_cls, handler, mode=mode)
            return handler

        return _wrap

    def register(
        self,
        event_cls: type[EventT],
        handler: Callable[[EventT], None],
        *,
        mode: SubscriberMode = "sync",
    ) -> None:
        """Explicit registration. Equivalent to the decorator."""
        if not hasattr(event_cls, "event_name"):
            raise TypeError(f"{event_cls.__name__} must declare a class-level 'event_name'")
        if mode == "async" and inspect.iscoroutinefunction(handler):
            raise TypeError(
                f"Async-mode handler {_qualname(handler)} must be a sync "
                "function — Celery executes handlers synchronously in a worker."
            )

        self._handlers.setdefault(event_cls, []).append(Subscription(handler=handler, mode=mode))
        self._events_by_name[event_cls.event_name] = event_cls
        self._handlers_by_name[_qualname(handler)] = handler

    # -- publish ----------------------------------------------------------

    def publish(self, event: Event) -> None:
        """Run sync handlers inline; queue async handlers via the dispatcher.

        Sync handler exceptions propagate so the publishing transaction
        rolls back. Async dispatch failures (e.g., broker down) are
        logged and re-raised — better to fail loudly than silently drop.
        """
        regs = self._handlers.get(type(event), [])
        if not regs:
            return

        log = self._log.bind(event_name=event.event_name)
        for reg in regs:
            if reg.mode == "sync":
                try:
                    reg.handler(event)
                except Exception:
                    log.exception(
                        "eventbus_sync_handler_failed",
                        handler=_qualname(reg.handler),
                    )
                    raise
            else:
                self._dispatch_async(event, reg.handler, log)

    def _dispatch_async(
        self,
        event: Event,
        handler: HandlerCallable,
        log: Any,
    ) -> None:
        if self._dispatcher is None:
            log.warning(
                "eventbus_no_dispatcher_configured",
                handler=_qualname(handler),
            )
            return
        self._dispatcher(
            handler_name=_qualname(handler),
            event_name=event.event_name,
            payload=event.model_dump(mode="json"),
        )

    # -- worker-side lookup ----------------------------------------------

    def resolve_handler(self, handler_name: str) -> HandlerCallable:
        """Look up a registered handler by its qualified name.

        Used by the Celery dispatch task to find the function the API
        process queued. Both processes register the same handlers at
        import time, so the names match.
        """
        try:
            return self._handlers_by_name[handler_name]
        except KeyError as exc:
            raise LookupError(f"No handler registered as {handler_name!r}") from exc

    def resolve_event(self, event_name: str) -> type[Event]:
        try:
            return self._events_by_name[event_name]
        except KeyError as exc:
            raise LookupError(f"No event registered as {event_name!r}") from exc

    # -- introspection / tests -------------------------------------------

    def handlers_for(self, event_cls: type[Event]) -> Iterable[Subscription]:
        return tuple(self._handlers.get(event_cls, ()))

    def clear(self) -> None:
        """Drop all registrations. Tests use this between cases."""
        self._handlers.clear()
        self._handlers_by_name.clear()
        self._events_by_name.clear()


def _qualname(handler: Callable[..., Any]) -> str:
    module = getattr(handler, "__module__", "?")
    qualname = getattr(handler, "__qualname__", repr(handler))
    return f"{module}:{qualname}"


_default_bus = EventBus()


def get_default_bus() -> EventBus:
    """Process-wide default bus. API and workers share this instance."""
    return _default_bus
