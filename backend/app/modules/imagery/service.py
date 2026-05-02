"""ImageryService Protocol + skeleton implementation.

Other modules consume `ImageryService` via DI and only this Protocol —
never the implementation. The `repository`, `models`, and provider
adapters are private.

PR-A lands the Protocol shape and a skeleton impl whose methods raise
`NotImplementedError`. PR-B fills the bodies as it builds the
SentinelHubProvider, the Celery ingestion pipeline, and the REST
endpoints. Splitting the contract from its body lets the Protocol
ship today without dragging in httpx / S3 / Celery dependencies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.imagery.providers.protocol import ImageryProvider
from app.modules.imagery.schemas import (
    IngestionJobRead,
    SubscriptionCreate,
    SubscriptionRead,
)


class ImageryService(Protocol):
    """Public contract for the imagery module."""

    async def create_subscription(
        self,
        *,
        block_id: UUID,
        payload: SubscriptionCreate,
        actor_user_id: UUID | None,
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
    ) -> None: ...

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
    ) -> tuple[UUID, ...]:
        """Enqueue discovery for every active subscription on the block.

        Returns the subscription IDs that were enqueued. Empty tuple
        means there are no active subscriptions to refresh.
        """
        ...

    async def list_scenes(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[IngestionJobRead, ...], str | None]:
        """Cursor-paginated list of ingestion jobs for a block.

        Returns (rows, next_cursor). `next_cursor` is None when the page
        is the last page.
        """
        ...


class ImageryServiceImpl:
    """Skeleton — real implementation lands in PR-B.

    The provider injection point is the constructor; PR-B's wiring
    will pass a `SentinelHubProvider` instance from the FastAPI
    application factory.
    """

    def __init__(self, *, provider: ImageryProvider) -> None:
        self._provider = provider

    async def create_subscription(
        self,
        *,
        block_id: UUID,
        payload: SubscriptionCreate,
        actor_user_id: UUID | None,
    ) -> SubscriptionRead:
        raise NotImplementedError("Implemented in PR-B")

    async def list_subscriptions(
        self,
        *,
        block_id: UUID,
        include_inactive: bool = False,
    ) -> tuple[SubscriptionRead, ...]:
        raise NotImplementedError("Implemented in PR-B")

    async def revoke_subscription(
        self,
        *,
        subscription_id: UUID,
        actor_user_id: UUID | None,
    ) -> None:
        raise NotImplementedError("Implemented in PR-B")

    async def trigger_refresh(
        self,
        *,
        block_id: UUID,
        actor_user_id: UUID | None,
    ) -> tuple[UUID, ...]:
        raise NotImplementedError("Implemented in PR-B")

    async def list_scenes(
        self,
        *,
        block_id: UUID,
        from_datetime: datetime | None = None,
        to_datetime: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[tuple[IngestionJobRead, ...], str | None]:
        raise NotImplementedError("Implemented in PR-B")
