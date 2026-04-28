"""Correlation ID middleware.

Reads X-Correlation-ID from the incoming request, generates a UUIDv4 if
missing, attaches it to:
  - request.state.correlation_id (for handlers and exception handlers)
  - structlog's contextvars (for every log line in this task)
  - OTel baggage (for downstream HTTP / Celery tasks)
And echoes it back on the response.

Per ARCHITECTURE.md § 14: "Correlation ID generated at NGINX ingress
(X-Correlation-ID), propagated through every internal call and into
Celery task headers."
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING

from opentelemetry import baggage, context as otel_context
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, unbind_contextvars

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

CORRELATION_HEADER = "X-Correlation-ID"
CORRELATION_BAGGAGE_KEY = "correlation_id"

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Return the correlation ID bound to the current task, if any."""
    return _correlation_id_ctx.get()


def _new_correlation_id() -> str:
    return str(uuid.uuid4())


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Read or generate a correlation ID and propagate it everywhere."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request.headers.get(CORRELATION_HEADER) or _new_correlation_id()
        request.state.correlation_id = correlation_id

        token = _correlation_id_ctx.set(correlation_id)
        bind_contextvars(correlation_id=correlation_id)

        otel_token = otel_context.attach(
            baggage.set_baggage(CORRELATION_BAGGAGE_KEY, correlation_id)
        )

        try:
            response = await call_next(request)
        finally:
            otel_context.detach(otel_token)
            unbind_contextvars("correlation_id")
            _correlation_id_ctx.reset(token)

        response.headers[CORRELATION_HEADER] = correlation_id
        return response
