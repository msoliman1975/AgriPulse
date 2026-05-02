"""ImageryService Protocol + concrete impl.

Other modules consume `ImageryService` via DI and only this Protocol —
never the implementation. The repository, models, and provider
adapters are private.

Endpoint paths in `router.py` translate HTTP into method calls; Celery
tasks in `tasks.py` are enqueued by `trigger_refresh()` (the on-demand
path) and by Beat (the scheduled path). Both routes flow through this
service for auditability.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.audit import AuditService, get_audit_service
from app.modules.imagery.errors import (
    SubscriptionNotFoundError,
)
from app.modules.imagery.events import (
    SubscriptionCreatedV1,
    SubscriptionRevokedV1,
)
from app.modules.imagery.repository import ImageryRepository
from app.modules.imagery.schemas import (
    IngestionJobRead,
    SubscriptionCreate,
    SubscriptionRead,
)
from app.shared.db.ids import uuid7
from app.shared.eventbus import EventBus, get_default_bus


class ImageryService(Protocol):
    """Public contract for the imagery module."""

    async def create_subscription(
        self,
        *,
        block_id: UUID,
        payload: SubscriptionCreate,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> SubscriptionRead: ...

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[SubscriptionRead, ...]: ...

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None: ...

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> tuple[UUID, ...]: ...

    async def list_scenes(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[IngestionJobRead, ...], str | None]: ...


class ImageryServiceImpl:
    """Concrete service. One per request — receives a tenant-scoped session."""

    def __init__(
        self,
        *,
        tenant_session: AsyncSession,
        audit_service: AuditService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._session = tenant_session
        self._repo = ImageryRepository(tenant_session)
        self._audit = audit_service or get_audit_service()
        self._bus = event_bus or get_default_bus()
        self._log = get_logger(__name__)

    # ---- Subscriptions ----------------------------------------------------

    async def create_subscription(
        self,
        *,
        block_id: UUID,
        payload: SubscriptionCreate,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> SubscriptionRead:
        subscription_id = uuid7()
        row = await self._repo.insert_subscription(
            subscription_id=subscription_id,
            block_id=block_id,
            product_id=payload.product_id,
            cadence_hours=payload.cadence_hours,
            cloud_cover_max_pct=payload.cloud_cover_max_pct,
            actor_user_id=actor_user_id,
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="imagery.subscription_created",
            actor_user_id=actor_user_id,
            subject_kind="imagery_subscription",
            subject_id=subscription_id,
            details={
                "block_id": str(block_id),
                "product_id": str(payload.product_id),
                "cadence_hours": payload.cadence_hours,
                "cloud_cover_max_pct": payload.cloud_cover_max_pct,
            },
            correlation_id=correlation_id,
        )
        self._bus.publish(
            SubscriptionCreatedV1(
                subscription_id=subscription_id,
                block_id=block_id,
                product_id=payload.product_id,
                actor_user_id=actor_user_id,
            )
        )
        return SubscriptionRead.model_validate(row)

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[SubscriptionRead, ...]:
        rows = await self._repo.list_subscriptions(
            block_id=block_id, include_inactive=include_inactive
        )
        return tuple(SubscriptionRead.model_validate(r) for r in rows)

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> None:
        before = await self._repo.get_subscription(subscription_id)
        if not before["is_active"]:
            return  # already revoked — idempotent, no audit row
        after = await self._repo.revoke_subscription(
            subscription_id=subscription_id, actor_user_id=actor_user_id
        )
        await self._audit.record(
            tenant_schema=tenant_schema,
            event_type="imagery.subscription_revoked",
            actor_user_id=actor_user_id,
            subject_kind="imagery_subscription",
            subject_id=subscription_id,
            details={"block_id": str(after["block_id"])},
            correlation_id=correlation_id,
        )
        self._bus.publish(
            SubscriptionRevokedV1(
                subscription_id=subscription_id,
                block_id=after["block_id"],
                actor_user_id=actor_user_id,
            )
        )

    # ---- Refresh ----------------------------------------------------------

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
        tenant_schema: str,
        correlation_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        """Enqueue `discover_scenes` for every active subscription on the block.

        Returns the list of subscription IDs we just enqueued. Empty
        tuple = there are no active subscriptions on this block.
        """
        # Local import: importing tasks.py at module level would pull
        # Celery into the FastAPI process tree at the wrong moment for
        # some startup orderings. Local import keeps service.py
        # Celery-free.
        from app.modules.imagery.tasks import discover_scenes

        subs = await self._repo.list_subscriptions(block_id=block_id, include_inactive=False)
        ids = tuple(sub["id"] for sub in subs)
        for subscription_id in ids:
            discover_scenes.delay(str(subscription_id), tenant_schema)
            await self._audit.record(
                tenant_schema=tenant_schema,
                event_type="imagery.refresh_triggered",
                actor_user_id=actor_user_id,
                subject_kind="imagery_subscription",
                subject_id=subscription_id,
                details={"block_id": str(block_id)},
                correlation_id=correlation_id,
            )
        return ids

    # ---- Scenes (read) ---------------------------------------------------

    async def list_scenes(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[IngestionJobRead, ...], str | None]:
        # Full implementation lands in PR-C alongside the GET /scenes
        # endpoint. PR-B keeps the Protocol method signature stable so
        # the router can already declare it.
        raise NotImplementedError("Scene listing lands in PR-C")


def get_imagery_service(
    *,
    tenant_session: AsyncSession,
    audit_service: AuditService | None = None,
    event_bus: EventBus | None = None,
) -> ImageryService:
    """Factory used by the router's FastAPI dependency."""
    return ImageryServiceImpl(
        tenant_session=tenant_session,
        audit_service=audit_service,
        event_bus=event_bus,
    )


# Suppress unused-import warning when these are referenced only inside
# Protocol annotations.
_ = (datetime, UTC, SubscriptionNotFoundError)
