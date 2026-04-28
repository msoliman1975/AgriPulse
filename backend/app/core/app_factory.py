"""FastAPI app factory.

Builds a fully-configured app instance: logging + tracing initialised,
middlewares installed, exception handlers registered, routers mounted.

Subsequent commits in PR 2 wire correlation, auth, RBAC, and module
routers into this factory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware

from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.observability import configure_tracing, instrument_app
from app.core.settings import get_settings
from app.shared.auth import AuthMiddleware
from app.shared.correlation import CorrelationIdMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App lifespan — startup and shutdown bookkeeping."""
    log = get_logger(__name__)
    log.info("app_startup", env=get_settings().app_env)
    try:
        yield
    finally:
        log.info("app_shutdown")


def create_app() -> FastAPI:
    """Construct the FastAPI app. Called by ASGI entrypoint and by tests."""
    configure_logging()
    configure_tracing()

    settings = get_settings()

    app = FastAPI(
        title="MissionAgre API",
        version="0.1.0",
        docs_url="/docs" if settings.app_debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_debug else None,
        lifespan=_lifespan,
    )

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Starlette wraps middleware in reverse order of addition: the LAST
    # add_middleware call becomes the outermost layer. Correlation must
    # run before auth so a 401 from invalid JWT still carries a
    # correlation ID in logs and the response header.
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    # NOTE: module routers are registered in subsequent commits within
    # PR 2 once modules/ exist.

    install_exception_handlers(app)
    instrument_app(app)

    @app.get("/health", status_code=status.HTTP_200_OK, tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe. No tenancy, no auth."""
        return {"status": "ok", "service": settings.service_name}

    return app
