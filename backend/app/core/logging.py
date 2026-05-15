"""Structured JSON logging via structlog.

Required fields per ARCHITECTURE.md § 14: timestamp, level, service,
correlation_id, tenant_id, user_id (when known), message. Correlation,
tenant, and user fields ride on a structlog contextvar bound by the
correlation and auth middlewares.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import (
    CallsiteParameter,
    CallsiteParameterAdder,
    JSONRenderer,
    StackInfoRenderer,
    TimeStamper,
    add_log_level,
    format_exc_info,
)
from structlog.stdlib import (
    BoundLogger,
    LoggerFactory,
    ProcessorFormatter,
    add_logger_name,
    filter_by_level,
)

from app.core.settings import get_settings


def _add_service(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    event_dict.setdefault("service", get_settings().service_name)
    return event_dict


def configure_logging() -> None:
    """Configure stdlib + structlog so every log line is JSON.

    Idempotent — safe to call from app factory and from worker bootstraps.
    """
    settings = get_settings()
    log_level = getattr(logging, settings.app_log_level)

    # Processors common to both pipelines (no logger-dependent ones).
    common_processors: list[structlog.types.Processor] = [
        merge_contextvars,
        add_logger_name,
        add_log_level,
        TimeStamper(fmt="iso", utc=True),
        _add_service,
        StackInfoRenderer(),
        format_exc_info,
        CallsiteParameterAdder(
            parameters={
                CallsiteParameter.MODULE,
                CallsiteParameter.FUNC_NAME,
                CallsiteParameter.LINENO,
            }
        ),
    ]

    structlog.configure(
        # structlog's own pipeline has a real BoundLogger, so filter_by_level
        # can safely call logger.isEnabledFor.
        processors=[filter_by_level, *common_processors, JSONRenderer()],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, third-party libs) through
    # the same JSON pipeline.
    #
    # filter_by_level is intentionally omitted from foreign_pre_chain:
    # ProcessorFormatter invokes the chain with logger=None for non-structlog
    # records, and filter_by_level would crash on None.isEnabledFor. The
    # underlying stdlib logger has already applied its level filter before
    # the record reaches this handler, so re-filtering here would also be
    # redundant. This used to produce ~thousands of tracebacks per minute
    # when the OTLP exporter bg-thread emitted warnings against an
    # unreachable Tempo endpoint.
    formatter = ProcessorFormatter(
        foreign_pre_chain=common_processors,
        processors=[ProcessorFormatter.remove_processors_meta, JSONRenderer()],
    )
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)

    # Tame the noisy ones.
    for name in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine", "asyncio"):
        logging.getLogger(name).setLevel(max(log_level, logging.INFO))


def get_logger(name: str | None = None) -> BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name) if name else structlog.get_logger()
