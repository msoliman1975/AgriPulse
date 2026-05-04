"""FastAPI app factory.

Builds a fully-configured app instance: logging + tracing initialised,
middlewares installed, exception handlers registered, routers mounted.

Subsequent commits in PR 2 wire correlation, auth, RBAC, and module
routers into this factory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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

    _register_module_routers(app)

    install_exception_handlers(app)
    instrument_app(app)

    @app.get("/health", status_code=status.HTTP_200_OK, tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe. No tenancy, no auth."""
        return {"status": "ok", "service": settings.service_name}

    return app


def _register_module_routers(app: FastAPI) -> None:
    """Mount each domain module's router. Imports are local to keep the
    factory's import graph thin in environments that do not need the
    full app (e.g., a Celery worker importing only `app.core.settings`).
    """
    from app.modules.farms.router import router as farms_router
    from app.modules.iam.router import router as iam_router
    from app.modules.imagery.router import router as imagery_router
    from app.modules.imagery.subscribers import (
        register_subscribers as register_imagery_subscribers,
    )
    from app.modules.indices.router import router as indices_router
    from app.modules.tenancy.router import router as tenancy_router
    from app.shared.eventbus import get_default_bus

    app.include_router(iam_router)
    app.include_router(tenancy_router)
    app.include_router(farms_router)
    app.include_router(imagery_router)
    app.include_router(indices_router)

    # Cross-module event subscribers — registered once per process.
    # Imagery's subscriber listens for BlockBoundaryChangedV1 from
    # farms and resets cached scenes accordingly.
    register_imagery_subscribers(get_default_bus())
