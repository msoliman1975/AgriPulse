"""OpenTelemetry tracing and Prometheus metrics setup.

Per ARCHITECTURE.md § 14:
  - OTLP/HTTP exporter to Tempo
  - prometheus-fastapi-instrumentator for HTTP RED metrics
  - Auto-instrumentation for FastAPI, SQLAlchemy, Celery, httpx
  - /metrics on a separate port (not exposed via ingress)
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import REGISTRY, make_asgi_app
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.settings import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

_tracer_provider_initialized = False
_tracer_provider_lock = threading.Lock()


def _resource() -> Resource:
    settings = get_settings()
    attrs: dict[str, str | int] = {
        "service.name": settings.otel_service_name,
        "service.version": "0.1.0",
    }
    for kv in settings.otel_resource_attributes.split(","):
        if "=" in kv:
            key, value = kv.split("=", 1)
            attrs[key.strip()] = value.strip()
    return Resource.create(attrs)


def configure_tracing() -> None:
    """Wire the OTel tracer provider with an OTLP/HTTP exporter.

    Idempotent. If no OTLP endpoint is configured (typical in unit tests),
    install a TracerProvider with no exporter so spans are still created
    and instrumentation contracts hold.
    """
    global _tracer_provider_initialized
    with _tracer_provider_lock:
        if _tracer_provider_initialized:
            return

        provider = TracerProvider(resource=_resource())
        endpoint = get_settings().otel_exporter_otlp_endpoint
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _tracer_provider_initialized = True


def instrument_app(app: FastAPI) -> None:
    """Attach FastAPI / SQLAlchemy / httpx OTel instrumentation and Prometheus."""
    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        excluded_handlers=["/metrics", "/health"],
    )
    instrumentator.instrument(app)


def metrics_asgi_app() -> object:
    """Return a standalone ASGI app exposing Prometheus /metrics.

    Mounted on a sidecar listener on the metrics port, not the public port,
    so the metrics endpoint is never reachable from the ingress.
    """
    return make_asgi_app(registry=REGISTRY)
