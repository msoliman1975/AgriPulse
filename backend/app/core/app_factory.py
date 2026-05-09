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
    # Sync decision-tree YAML files into the public catalog so a fresh
    # process picks up authored changes without a manual migration. The
    # loader is idempotent — same content on disk → no DB writes.
    try:
        from app.modules.recommendations.loader import sync_from_disk
        from app.shared.db.session import AsyncSessionLocal

        factory = AsyncSessionLocal()
        async with factory() as session:
            await sync_from_disk(session)
    except Exception as exc:  # noqa: BLE001
        log.warning("decision_trees_sync_failed", error=str(exc))
    # PR-Reorg6: cold-start platform-admin bootstrap. Idempotent —
    # only fires when zero active PlatformAdmins exist.
    try:
        from app.modules.platform_admins.bootstrap import (
            bootstrap_platform_admin,
        )

        await bootstrap_platform_admin(get_settings())
    except Exception as exc:  # noqa: BLE001
        log.warning("platform_admin_bootstrap_lifespan_error", error=str(exc))
    try:
        yield
    finally:
        log.info("app_shutdown")


def create_app() -> FastAPI:
    """Construct the FastAPI app. Called by ASGI entrypoint and by tests."""
    configure_logging()
    configure_tracing()

    # Construct a publisher-side Celery app so `@shared_task.delay(...)`
    # calls from API endpoints (e.g. POST /imagery/refresh) resolve to
    # our configured Redis broker. Without this, the implicit default
    # app falls through to `amqp://localhost:5672` and 500s with
    # `Connection refused` when the API tries to enqueue work.
    from workers.celery_factory import build_publisher

    build_publisher()

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
    from app.modules.alerts.router import router as alerts_router
    from app.modules.farms.router import router as farms_router
    from app.modules.iam.router import router as iam_router
    from app.modules.imagery.router import router as imagery_router
    from app.modules.integrations.router import router as integrations_router
    from app.modules.platform_admins.router import (
        router as platform_admins_router,
    )
    from app.modules.platform_admins.admins_router import (
        router as platform_admins_self_router,
    )
    from app.modules.platform_admins.tenant_integrations import (
        router as platform_tenant_integrations_router,
    )
    from app.modules.platform_defaults.router import (
        router as platform_defaults_router,
    )
    from app.modules.integrations_health.router import (
        router as integrations_health_router,
    )
    from app.modules.imagery.subscribers import (
        register_subscribers as register_imagery_subscribers,
    )
    from app.modules.indices.router import router as indices_router
    from app.modules.irrigation.router import router as irrigation_router
    from app.modules.notifications.router import router as notifications_router
    from app.modules.notifications.subscribers import (
        register_subscribers as register_notifications_subscribers,
    )
    from app.modules.plans.router import router as plans_router
    from app.modules.recommendations.router import router as recommendations_router
    from app.modules.signals.router import router as signals_router
    from app.modules.tenancy.router import router as tenancy_router
    from app.modules.weather.router import router as weather_router
    from app.shared.eventbus import get_default_bus

    app.include_router(iam_router)
    app.include_router(tenancy_router)
    app.include_router(farms_router)
    app.include_router(imagery_router)
    app.include_router(indices_router)
    app.include_router(weather_router)
    app.include_router(alerts_router)
    app.include_router(plans_router)
    app.include_router(irrigation_router)
    app.include_router(notifications_router)
    app.include_router(recommendations_router)
    app.include_router(signals_router)
    app.include_router(integrations_health_router)
    app.include_router(integrations_router)
    app.include_router(platform_defaults_router)
    app.include_router(platform_admins_router)
    app.include_router(platform_tenant_integrations_router)
    app.include_router(platform_admins_self_router)

    # Cross-module event subscribers — registered once per process.
    # Imagery's subscriber listens for BlockBoundaryChangedV1 from
    # farms and resets cached scenes accordingly. Notifications listens
    # for AlertOpenedV1 and fans out per-channel dispatches.
    bus = get_default_bus()
    register_imagery_subscribers(bus)
    register_notifications_subscribers(bus)
