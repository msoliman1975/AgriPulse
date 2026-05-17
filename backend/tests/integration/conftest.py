"""Integration-test fixtures.

Spins up a single PostgreSQL+TimescaleDB+PostGIS container, a Redis
container, and a MailHog SMTP sink per test session. Migrations run
once at module import; each test gets its own AsyncSession.

Skipped if Docker / testcontainers are not available â€” the marker
`integration` lets CI gate this whole tree on presence of containers.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

try:
    from testcontainers.core.container import DockerContainer  # type: ignore[import-untyped]
    from testcontainers.core.waiting_utils import wait_for_logs  # type: ignore[import-untyped]
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
    from testcontainers.redis import RedisContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    DockerContainer = None  # type: ignore[assignment]
    PostgresContainer = None  # type: ignore[assignment]
    RedisContainer = None  # type: ignore[assignment]
    wait_for_logs = None  # type: ignore[assignment]


# Image with TimescaleDB + PostGIS already installed; pgcrypto and citext
# are bundled with stock Postgres.
_TIMESCALE_IMAGE = "timescale/timescaledb-ha:pg16"


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[object]:
    if PostgresContainer is None:  # pragma: no cover
        pytest.skip("testcontainers not installed")
    # `driver="psycopg"` matches our psycopg[binary] dep â€” without it
    # testcontainers falls back to psycopg2 for its readiness probe.
    container = PostgresContainer(_TIMESCALE_IMAGE, driver="psycopg")
    container.with_env("POSTGRES_DB", "agripulse_test")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_container() -> Iterator[object]:
    if RedisContainer is None:  # pragma: no cover
        pytest.skip("testcontainers not installed")
    container = RedisContainer("redis:7-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mailhog_container() -> Iterator[object]:
    """SMTP sink for the notifications email channel.

    Without it, ``send_email`` raises ``Connection refused`` and the
    fan-out tests record ``status='failed'`` instead of ``'sent'``.
    """
    if DockerContainer is None:  # pragma: no cover
        pytest.skip("testcontainers not installed")
    container = DockerContainer("mailhog/mailhog:v1.0.1").with_exposed_ports(1025, 8025)
    container.start()
    wait_for_logs(container, "Creating API v2")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session", autouse=True)
def _wire_settings(
    postgres_container: object,
    redis_container: object,
    mailhog_container: object,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[None]:
    """Point Settings at the live containers, then run public migrations."""
    pg = postgres_container
    redis = redis_container

    # testcontainers exposes `get_connection_url()` returning a sync DSN
    # in psycopg form. Swap drivers to make the async/sync URLs.
    sync_url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")  # type: ignore[attr-defined]
    async_url = sync_url.replace("postgresql+psycopg", "postgresql+asyncpg")
    redis_url = f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0"  # type: ignore[attr-defined]

    os.environ["DATABASE_URL"] = async_url
    os.environ["DATABASE_SYNC_URL"] = sync_url
    os.environ["REDIS_URL"] = redis_url
    mh = mailhog_container
    os.environ["SMTP_HOST"] = mh.get_container_host_ip()  # type: ignore[attr-defined]
    os.environ["SMTP_PORT"] = str(mh.get_exposed_port(1025))  # type: ignore[attr-defined]
    os.environ["SMTP_STARTTLS"] = "false"
    os.environ["SMTP_USERNAME"] = ""
    os.environ["SMTP_PASSWORD"] = ""
    # Point Celery broker at the test Redis so module-side `.delay()`
    # calls â€” e.g. weather.fetch_weather chaining derive_weather_daily â€”
    # enqueue against a reachable broker instead of falling through to
    # the default amqp://localhost. No worker consumes the queue in the
    # test process; tasks are direct-invoked through their `_async`
    # cores when behavior matters.
    os.environ["CELERY_BROKER_URL"] = redis_url
    os.environ["CELERY_RESULT_BACKEND"] = redis_url
    os.environ["APP_ENV"] = "test"

    from app.core.settings import get_settings

    get_settings.cache_clear()

    # Construct the publisher-side Celery app so `@shared_task.delay(...)`
    # resolves to the configured broker. Without this, `current_app`
    # is Celery's implicit default with no broker -> connection refused.
    from workers.celery_factory import build_publisher

    build_publisher()

    # Run public migrations once for the session.
    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_root / "alembic.ini"), ini_section="public")
    command.upgrade(cfg, "head")

    yield

    # Drop async engine â€” keeps pytest from leaking pool connections.
    import asyncio

    from app.shared.db.session import dispose_engine

    asyncio.run(dispose_engine())


@pytest.fixture
async def admin_session() -> AsyncIterator[object]:
    """Public-schema admin session for direct DB inspection."""
    from app.shared.db.session import AsyncSessionLocal

    factory = AsyncSessionLocal()
    async with factory() as session:
        yield session
