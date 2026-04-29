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

    shared_processors: list[structlog.types.Processor] = [
        merge_contextvars,
        filter_by_level,
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
        processors=[*shared_processors, JSONRenderer()],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, third-party libs) through
    # the same JSON pipeline.
    formatter = ProcessorFormatter(
        foreign_pre_chain=shared_processors,
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
