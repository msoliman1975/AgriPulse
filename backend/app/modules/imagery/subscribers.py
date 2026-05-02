"""Cross-module event subscribers for the imagery module.

The only cross-module reaction in PR-B is BlockBoundaryChangedV1 from
the farms module: when a block's polygon changes, every active
subscription on that block has stale scenes (cached against the old
aoi_hash). Reset their `last_successful_ingest_at` so the next
discovery refetches.

We do NOT delete past `imagery_ingestion_jobs` rows — the historical
record stays. Re-discovery just creates new pending jobs against the
new aoi_hash.

Subscribers register at app startup via `register_subscribers(bus)`,
called from `app.core.app_factory`.

Why sync SQLAlchemy here: the EventBus dispatches sync handlers inline
in the publisher's call stack. The publishing context is FastAPI's
async route or a Celery task — both already own a running event loop,
so we can't `asyncio.run` an async function from inside the handler.
A small synchronous engine + session lets the handler run without
caring about the surrounding loop. The query is one UPDATE per active
tenant; the table is tiny.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.modules.farms.events import BlockBoundaryChangedV1
from app.shared.db.session import sanitize_tenant_schema
from app.shared.eventbus import EventBus

_log = get_logger(__name__)

# Lazily built sync engine — one per process. We don't reuse
# `app.shared.db.session.get_engine()` because that's the async engine,
# bound to a specific event loop.
_sync_engine = None
_sync_factory: sessionmaker[Session] | None = None


def _session_factory() -> sessionmaker[Session]:
    global _sync_engine, _sync_factory
    if _sync_factory is None:
        settings = get_settings()
        _sync_engine = create_engine(
            str(settings.database_sync_url),
            pool_pre_ping=True,
            future=True,
        )
        _sync_factory = sessionmaker(bind=_sync_engine, autoflush=False, future=True)
    return _sync_factory


def _on_block_boundary_changed(event: BlockBoundaryChangedV1) -> None:
    """Reset subscriptions' last_successful_ingest_at for the affected block.

    Walks every active tenant and runs one UPDATE per schema. The
    matching tenant updates one or more rows; the rest are zero-row
    no-ops. This avoids coupling the farms event payload to tenancy
    by adding a `tenant_schema` field.
    """
    factory = _session_factory()
    block_id: UUID = event.block_id

    with factory() as admin_session:
        schemas = [
            str(r[0])
            for r in admin_session.execute(
                text(
                    "SELECT schema_name FROM public.tenants "
                    "WHERE status = 'active' AND deleted_at IS NULL"
                )
            ).all()
        ]

    total_updated = 0
    for schema in schemas:
        try:
            sanitize_tenant_schema(schema)
        except ValueError:
            continue
        with factory() as session:
            session.execute(text(f"SET LOCAL search_path TO {schema}, public"))
            result = session.execute(
                text(
                    "UPDATE imagery_aoi_subscriptions "
                    "SET last_successful_ingest_at = NULL "
                    "WHERE block_id = :bid "
                    "  AND is_active = TRUE AND deleted_at IS NULL"
                ),
                {"bid": block_id},
            )
            session.commit()
            rowcount = getattr(result, "rowcount", 0) or 0
            total_updated += int(rowcount)
    if total_updated:
        _log.info(
            "imagery_invalidated_on_boundary_change",
            block_id=str(block_id),
            subscriptions_reset=total_updated,
        )


def register_subscribers(bus: EventBus) -> None:
    """Register imagery's cross-module event handlers on the bus.

    Called once at app startup from `app.core.app_factory`. Idempotent:
    re-registering during a test reset clears and re-attaches.
    """
    bus.register(BlockBoundaryChangedV1, _on_block_boundary_changed, mode="sync")
