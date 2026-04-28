"""Celery task that drives async event bus subscribers in worker processes.

Flow:

  API process:
    bus.publish(event)
      → for each async subscription:
          dispatcher(handler_name, event_name, payload)
          → CeleryDispatcher implementation calls
              eventbus_dispatch.delay(handler_name, event_name, payload)

  Worker process:
    eventbus_dispatch.run(handler_name, event_name, payload)
      → bus = get_default_bus()
      → event_cls = bus.resolve_event(event_name)
      → handler   = bus.resolve_handler(handler_name)
      → handler(event_cls(**payload))

Both processes import the same handler modules at startup, so name
lookups always resolve.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from app.core.logging import get_logger
from app.shared.eventbus import get_default_bus

_log = get_logger(__name__)


@shared_task(name="eventbus.dispatch", bind=False, ignore_result=True)
def eventbus_dispatch(handler_name: str, event_name: str, payload: dict[str, Any]) -> None:
    """Re-hydrate an event and run a single async-mode subscriber."""
    bus = get_default_bus()
    event_cls = bus.resolve_event(event_name)
    handler = bus.resolve_handler(handler_name)
    handler(event_cls(**payload))
    _log.info(
        "eventbus_async_handled",
        event_name=event_name,
        handler=handler_name,
    )


def celery_dispatcher(*, handler_name: str, event_name: str, payload: dict[str, Any]) -> None:
    """Implements the CeleryDispatcher Protocol against `eventbus_dispatch`.

    Wired into the bus from the app/celery startup code via
    ``get_default_bus().set_dispatcher(celery_dispatcher)``.
    """
    eventbus_dispatch.delay(handler_name, event_name, payload)
