"""Integration-test fixtures.

Spins up a single PostgreSQL+TimescaleDB+PostGIS container and a Redis
container per test session. Migrations run once at module import; each
test gets its own AsyncSession.

Skipped if Docker / testcontainers are not available — the marker
`integration` lets CI gate this whole tree on presence of containers.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]
    from testcontainers.redis import RedisContainer  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    PostgresContainer = None  # type: ignore[assignment]
    RedisContainer = None  # type: ignore[assignment]


# Image with TimescaleDB + PostGIS already installed; pgcrypto and citext
# are bundled with stock Postgres.
_TIMESCALE_IMAGE = "timescale/timescaledb-ha:pg16"


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[object]:
    if PostgresContainer is None:  # pragma: no cover
        pytest.skip("testcontainers not installed")
    # `driver="psycopg"` matches our psycopg[binary] dep — without it
    # testcontainers falls back to psycopg2 for its readiness probe.
    container = PostgresContainer(_TIMESCALE_IMAGE, driver="psycopg")
    container.with_env("POSTGRES_DB", "missionagre_test")
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


@pytest.fixture(scope="session", autouse=True)
def _wire_settings(
    postgres_container: object,
    redis_container: object,
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
    os.environ["APP_ENV"] = "test"

    from app.core.settings import get_settings

    get_settings.cache_clear()

    # Run public migrations once for the session.
    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_root / "alembic.ini"), ini_section="public")
    command.upgrade(cfg, "head")

    yield

    # Drop async engine — keeps pytest from leaking pool connections.
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
