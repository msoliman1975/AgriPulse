"""RFC 7807 application/problem+json error model and FastAPI handlers.

Per ARCHITECTURE.md § 8: every error response uses problem+json shape.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


class Problem(BaseModel):
    """RFC 7807 problem+json body."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(default="about:blank", description="A URI identifying the problem type.")
    title: str = Field(description="A short, human-readable summary of the problem type.")
    status: int = Field(description="The HTTP status code.")
    detail: str | None = Field(default=None, description="Human-readable explanation.")
    instance: str | None = Field(default=None, description="URI reference for this occurrence.")
    correlation_id: str | None = Field(
        default=None, description="Request correlation ID for log/trace lookup."
    )


class APIError(Exception):
    """Application-level exception that converts cleanly to a Problem response."""

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str | None = None,
        type_: str = "about:blank",
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.type = type_
        self.extras = extras or {}


def _correlation_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def _problem_response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    problem = Problem(
        type=exc.type,
        title=exc.title,
        status=exc.status_code,
        detail=exc.detail,
        instance=str(request.url),
        correlation_id=_correlation_id(request),
        **exc.extras,
    )
    return _problem_response(problem)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    problem = Problem(
        title=exc.detail if isinstance(exc.detail, str) else "HTTP error",
        status=exc.status_code,
        detail=str(exc.detail) if exc.detail is not None else None,
        instance=str(request.url),
        correlation_id=_correlation_id(request),
    )
    return _problem_response(problem)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    problem = Problem(
        type="https://missionagre.io/problems/validation",
        title="Request validation failed",
        status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="One or more request fields failed validation.",
        instance=str(request.url),
        correlation_id=_correlation_id(request),
    )
    body = problem.model_dump(exclude_none=True)
    body["errors"] = exc.errors()
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler.

    Avoids leaking stack traces to clients; logs the exception with the
    correlation ID so operators can trace it in Loki/Tempo.
    """
    from app.core.logging import get_logger

    get_logger(__name__).exception(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
    )
    problem = Problem(
        type="https://missionagre.io/problems/internal",
        title="Internal server error",
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred. The error has been logged.",
        instance=str(request.url),
        correlation_id=_correlation_id(request),
    )
    return _problem_response(problem)


def install_exception_handlers(app: FastAPI) -> None:
    """Register the four problem+json error handlers on the FastAPI app."""
    app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
